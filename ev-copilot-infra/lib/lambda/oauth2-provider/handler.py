"""
Custom Resource handler: creates/deletes an AgentCore OAuth2 credential provider.

Used by CDK to register Cognito credentials with AgentCore's token vault so
the Gateway can authenticate to the Runtime using OAuth.

Lifecycle:
  - Create: look up the Cognito client secret and create the provider.
    PhysicalResourceId = provider ARN.
  - Update: no-op when the properties are unchanged; otherwise (re)create the
    provider. If the provider name changed, CloudFormation sends a follow-up
    Delete for the old physical id, which removes the old provider.
  - Delete: delete the provider identified by the PhysicalResourceId (never by
    the current properties), so a follow-up Delete after a replacement cannot
    remove the new provider.
"""

import json
import logging
import urllib.request

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Properties CloudFormation adds itself — ignored when diffing old vs new props.
_IGNORED_PROPERTIES = {"ServiceToken"}

# Provider ARNs look like:
#   arn:aws:bedrock-agentcore:<region>:<account>:token-vault/default/oauth2credentialprovider/<name>
_PROVIDER_ARN_MARKER = "/oauth2credentialprovider/"


def send_cfn_response(event, context, status, data=None, reason=""):
    physical_id = (
        (data or {}).get("credentialProviderArn")
        or event.get("PhysicalResourceId")
        or context.log_stream_name
    )
    body = json.dumps({
        "Status": status,
        "Reason": reason or f"See CloudWatch Log Stream: {context.log_stream_name}",
        "PhysicalResourceId": physical_id,
        "StackId": event["StackId"],
        "RequestId": event["RequestId"],
        "LogicalResourceId": event["LogicalResourceId"],
        "Data": data or {},
    }).encode("utf-8")

    req = urllib.request.Request(
        event["ResponseURL"], data=body, method="PUT",
        headers={"Content-Type": ""},
    )
    urllib.request.urlopen(req)


def _relevant_props(props):
    """Return the resource properties without CloudFormation-managed keys."""
    return {k: v for k, v in (props or {}).items() if k not in _IGNORED_PROPERTIES}


def _provider_name_from_physical_id(physical_id):
    """Extract the provider name from a provider ARN physical id.

    Returns None when the physical id is not a provider ARN (e.g. the log
    stream name used when a Create failed before a provider existed).
    """
    if physical_id and _PROVIDER_ARN_MARKER in physical_id:
        return physical_id.rsplit("/", 1)[-1]
    return None


def _delete_provider(control_client, name):
    try:
        control_client.delete_oauth2_credential_provider(name=name)
        logger.info("Deleted OAuth2 provider: %s", name)
    except Exception:
        logger.warning("Could not delete provider %s (may not exist)", name)


def _create_provider(cognito_client, control_client, props, region):
    # Look up the Cognito client secret
    desc = cognito_client.describe_user_pool_client(
        UserPoolId=props["UserPoolId"],
        ClientId=props["ClientId"],
    )
    client_secret = desc["UserPoolClient"]["ClientSecret"]

    discovery_url = (
        f"https://cognito-idp.{region}.amazonaws.com/"
        f"{props['UserPoolId']}/.well-known/openid-configuration"
    )

    resp = control_client.create_oauth2_credential_provider(
        name=props["ProviderName"],
        credentialProviderVendor="CustomOauth2",
        oauth2ProviderConfigInput={
            "customOauth2ProviderConfig": {
                "oauthDiscovery": {
                    "discoveryUrl": discovery_url,
                },
                "clientId": props["ClientId"],
                "clientSecret": client_secret,
            }
        },
    )
    provider_arn = resp["credentialProviderArn"]
    logger.info("Created OAuth2 provider: %s", provider_arn)
    return provider_arn


def lambda_handler(event, context):
    try:
        logger.info("Event: %s", json.dumps(event, default=str))
        props = event["ResourceProperties"]
        request_type = event["RequestType"]
        physical_id = event.get("PhysicalResourceId")

        region = props["Region"]
        cognito_client = boto3.client("cognito-idp", region_name=region)
        control_client = boto3.client("bedrock-agentcore-control", region_name=region)

        if request_type == "Create":
            provider_arn = _create_provider(cognito_client, control_client, props, region)
            send_cfn_response(event, context, "SUCCESS", {
                "credentialProviderArn": provider_arn,
            })

        elif request_type == "Update":
            old_props = event.get("OldResourceProperties", {})
            old_name = _provider_name_from_physical_id(physical_id)

            # Nothing changed — keep the existing provider (no delete + recreate)
            if old_name and _relevant_props(old_props) == _relevant_props(props):
                logger.info("Properties unchanged — keeping provider %s", physical_id)
                send_cfn_response(event, context, "SUCCESS", {
                    "credentialProviderArn": physical_id,
                })
                return

            # Provider names are unique: when the name is unchanged the old
            # provider must be removed before it can be recreated. When the
            # name changed, CloudFormation deletes the old one afterwards.
            if old_name == props["ProviderName"]:
                _delete_provider(control_client, old_name)

            provider_arn = _create_provider(cognito_client, control_client, props, region)
            send_cfn_response(event, context, "SUCCESS", {
                "credentialProviderArn": provider_arn,
            })

        elif request_type == "Delete":
            name = _provider_name_from_physical_id(physical_id)
            if name:
                _delete_provider(control_client, name)
            else:
                logger.info(
                    "Physical id %s is not a provider ARN — nothing to delete", physical_id,
                )
            send_cfn_response(event, context, "SUCCESS")

        else:
            send_cfn_response(
                event, context, "FAILED", reason=f"Unsupported RequestType: {request_type}",
            )

    except Exception as e:
        logger.exception("Custom resource handler failed")
        try:
            send_cfn_response(event, context, "FAILED", reason=str(e))
        except Exception:
            # Last resort — nothing else can be done; CloudFormation will time out.
            logger.exception("Failed to send CloudFormation response")

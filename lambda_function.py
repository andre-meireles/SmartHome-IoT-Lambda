"""Lambda Function Source Code

Adheres to Smart Home Skill V3 API
Responds to discovery and control requests
"""

# Import AWS SDK and set up client
import uuid
import time
import boto3
import json

client = boto3.client('iot')
client_data = boto3.client('iot-data')

# Main Lambda handler
# First function invoked when service executes code
def lambda_handler(request, context):
    if request["directive"]["header"]["namespace"] == "Alexa.Discovery":
        return handleDiscovery(request)
    else:
        return handleNonDiscovery(request)

# Discovery handler
# Handles requests such as "Discover my devices"
def handleDiscovery(request):

    # Get list of things in IoT registry
    response = client.list_things()["things"]
    endpoints = []

    # Create list of endpoints
    for item in response:
        thingName = item["thingName"]
        item_info = getEndpoint(thingName)
        endpoints.append(item_info)

    # Response should include proper header + payload consisting of devices (if any) discovered
    response = {
        "event": {
            "header": {
                "namespace": "Alexa.Discovery",
                "name": "Discover.Response",
                "payloadVersion": "3",
                "messageId": getUUID()
            },
            "payload": {
                "endpoints": endpoints
            }
        }
    }
    return response

# NonDiscovery handler
# Handles requests that are not discovery
def handleNonDiscovery(request):
    request_namespace = request["directive"]["header"]["namespace"]
    request_name = request["directive"]["header"]["name"]

    if request_namespace == "Alexa.PowerController":
        return handlePowerController(request)

    elif request_namespace == "Alexa" and request_name == "ReportState":
        return handleReportState(request)

    # Send back error response if neither of these cases are met
    else:
        error_response = {
            "event": {
                "header": {
                  "namespace": "Alexa",
                  "name": "ErrorResponse",
                  "messageId": getUUID(),
                  "payloadVersion": "3"
                },
                "endpoint": {},
                "payload": {
                  "type": "INVALID_DIRECTIVE",
                  "message": "Directive is invalid"
                }
            }
        }
        return error_response

# PowerController handler
# handlePowerController: Handles requests such as "Turn on/off light"
def handlePowerController(request):

    request_name = request["directive"]["header"]["name"]
    endpoint_id = request["directive"]["endpoint"]["endpointId"]
    correlation_token = request["directive"]["header"]["correlationToken"]

    # Check if endpointId exists -> if not, immediately return error response
    try:
        client.describe_thing(thingName=endpoint_id)
    except:
        error_response = {
            "event": {
                "header": {
                    "namespace": "Alexa",
                    "name": "ErrorResponse",
                    "payloadVersion": "3",
                    "messageId": getUUID(),
                    "correlationToken": correlation_token
                },
                "endpoint": {
                    "scope": {
                        "type": "DirectedUserId",
                        "directedUserId": ""
                    },
                    "endpointId": endpoint_id
                },
                "payload": {
                    "type": "NO_SUCH_ENDPOINT",
                    "message": "Unable to reach " + endpoint_id + " because it does not exist"
                }
            }
        }
        return error_response

    # Update device shadow based on request type
    onVal = '1'
    onState = ''
    value = ""
    if request_name == "TurnOn":
        onVal = '0'
        onState = 'true'
        value = "ON"
    elif request_name == "TurnOff":
        onVal = '1'
        onState = 'false'
        value = "OFF"
    # If request name is invalid -> immediately return error response
    else:
        error_response = {
            "event": {
                "header": {
                    "namespace": "Alexa",
                    "name": "ErrorResponse",
                    "messageId": getUUID(),
                    "payloadVersion": "3"
                },
                "endpoint": {},
                "payload": {
                    "type": "INVALID_DIRECTIVE",
                    "message": "Directive is invalid"
                }
            }
        }
        return error_response
    desiredShadowJSON = '{"state":{"desired":{"on":' + onState + '}}}'
    publishPayload = '{"gpio":{"pin":2,"state":' + onVal + '}}'
    client_data.update_thing_shadow(thingName=endpoint_id, payload=desiredShadowJSON)
    client_data.publish(topic='/request', qos=0, payload=publishPayload)
    # Otherwise the turnOn/turnOff request was successful
    response = {
        "context": {
            "properties": [
                {
                    "namespace": "Alexa.PowerController",
                    "name": "powerState",
                    "value": value,
                    "timeOfSample": getUTCTimestamp(),
                    "uncertaintyInMilliseconds": 500
                }
            ]
        },
        "event": {
            "header": {
                "namespace": "Alexa",
                "name": "Response",
                "payloadVersion": "3",
                "messageId": getUUID(),
                "correlationToken": correlation_token
            },
            "endpoint": {
                "scope": {
                    "type": "DirectedUserId",
                    "directedUserId": ""
                },
                "endpointId": endpoint_id
            },
            "payload": {}
        }
    }

    return response

# ReportState Handler
# handleReportState: Response to state query from GUI
def handleReportState(request):
    # Get endpoint information
    endpoint_id = request["directive"]["endpoint"]["endpointId"]
    endpoint = getEndpoint(endpoint_id)
    correlation_token = request["directive"]["header"]["correlationToken"]

    # Determine state for all capabilities
    context_properties = []

    for capability in endpoint["capabilities"]:
        interface = capability["interface"]
        supported_properties = capability["properties"]["supported"]

        for supported_property in supported_properties:
            context_property_name = supported_property["name"]

            if interface == "Alexa.PowerController":
                if context_property_name == "powerState":
                    # Read from device shadow to determine state
                    currentShadow = client_data.get_thing_shadow(thingName=endpoint_id)
                    currentPayload = json.loads(currentShadow["payload"].read())
                    currentState = currentPayload["state"]["reported"]["on"]
                    if currentState:
                        value = "ON"
                    else:
                        value = "OFF"

                context_property = {
                    "namespace": interface,
                    "name": context_property_name,
                    "value": value,
                    "timeOfSample": getUTCTimestamp(),
                    "uncertaintyInMilliseconds": 500
                }

                context_properties.append(context_property)

    # Response includes context and event information
    response = {
        "context": {
            "properties": context_properties
        },
        "event": {
            "header": {
                "namespace": "Alexa",
                "name": "StateReport",
                "payloadVersion": "3",
                "messageId": getUUID(),
                "correlationToken": correlation_token
            },
            "endpoint": {
                "scope": {
                    "type": "DirectedUserId",
                    "directedUserId": ""
                },
                 "endpointId": endpoint_id
            },
            "payload": {}
        }
    }
    return response

# Helper function that gets information about the endpoint, based on endpointId
def getEndpoint(thingName):
    displayCategories = []
    capabilities = []
    manufacturerName = ""
    description = ""
    if "esp8266" in thingName.lower() or "light" in thingName.lower():
        displayCategories = ["LIGHT"]
        capabilities = [{
            "type": "AlexaInterface",
            "interface": "Alexa.PowerController",
            "version": "3",
            "properties": {
                "supported": [ {
                    "name": "powerState"
                }],
        "proactivelyReported": "true",
                "retrievable": "true"
            }
        }]
        manufacturerName = "Espressif Systems"
        description = "Light that turns on/off"
    item_info = {
        "endpointId": thingName,
        "manufacturerName": manufacturerName,
        "friendlyName": thingName,
        "description": description,
        "displayCategories": displayCategories,
        "cookie": {},
        "capabilities": capabilities
    }
    return item_info

# Utility functions
def getUUID():
    return str(uuid.uuid4())

def getUTCTimestamp(seconds=None):
    return time.strftime("%Y-%m-%dT%H:%M:%S.00Z", time.gmtime(seconds))

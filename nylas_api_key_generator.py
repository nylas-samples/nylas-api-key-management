import base64
import json
import time
import secrets
import string
import hashlib
import argparse
import os
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding, utils
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Get constants from environment variables
PRIVATE_KEY_BASE64 = os.environ.get("NYLAS_PRIVATE_KEY_BASE64")
PRIVATE_KEY_ID = os.environ.get("NYLAS_PRIVATE_KEY_ID")
APP_ID = os.environ.get("NYLAS_APP_ID")
NYLAS_API_URL = os.environ.get("NYLAS_API_URL")
BASE_PATH = f"/v3/admin/applications/{APP_ID}/api-keys"



def generate_nonce():
    """Generate a 20-character secure nonce."""
    chars = string.ascii_letters + string.digits
    return ''.join(secrets.choice(chars) for _ in range(20))


def canonical_json(data):
    """
    Produce a minified JSON string with keys sorted alphabetically.
    This ensures consistency in the string representation for signing.
    """
    return json.dumps(data, separators=(',', ':'), sort_keys=True)


def load_private_key():
    """Load the RSA private key from the Base64-encoded PEM."""
    try:
        private_key_pem = base64.b64decode(PRIVATE_KEY_BASE64)
        private_key = serialization.load_pem_private_key(
            private_key_pem,
            password=None,
        )
        return private_key
    except Exception as e:
        print(f"Error loading private key: {e}")
        return None


def generate_signature(path, method, payload=None, debug=False):
    """
    Generate a signature for the Nylas Admin API request.
    
    Args:
        path: API endpoint path
        method: HTTP method (GET, POST, DELETE, etc.)
        payload: Optional JSON payload for POST/PUT requests
        debug: Whether to print debug information
        
    Returns:
        dict: Headers and request information needed for the API call
    """
    private_key = load_private_key()
    if not private_key:
        return None
    
    # Generate timestamp & nonce
    timestamp = int(time.time())
    nonce = generate_nonce()
    
    # Create canonical data
    canonical_data = {
        "path": path,
        "method": method.lower(),
        "timestamp": timestamp,
        "nonce": nonce
    }
    
    # Add payload for POST/PUT requests
    payload_json = None
    if payload and method.lower() in ["post", "put"]:
        payload_json = canonical_json(payload)
        canonical_data["payload"] = payload_json
    
    # Create canonical JSON string
    canonical_json_str = canonical_json(canonical_data)
    
    if debug:
        print("Canonical JSON Before Signing:", canonical_json_str)
    
    # Hash the canonical JSON string using SHA-256
    hashed = hashlib.sha256(canonical_json_str.encode('utf-8')).digest()
    
    if debug:
        print("Signing Hash:", hashed.hex())
    
    # Sign the hash using RSA with PKCS1v15
    try:
        signature = private_key.sign(
            hashed,
            padding.PKCS1v15(),
            utils.Prehashed(hashes.SHA256())
        )
    except Exception as e:
        print(f"Error signing data: {e}")
        return None
    
    # Encode the signature in Base64
    signature_b64 = base64.b64encode(signature).decode('utf-8')
    
    # Create result with headers and request information
    result = {
        "headers": {
            "X-Nylas-Signature": signature_b64,
            "X-Nylas-Nonce": nonce,
            "X-Nylas-Timestamp": timestamp,
            "X-Nylas-Kid": PRIVATE_KEY_ID
        },
        "request_info": {
            "path": path,
            "method": method,
            "timestamp": timestamp,
            "nonce": nonce,
            "signature": signature_b64
        }
    }
    
    if payload_json:
        result["request_info"]["payload"] = payload_json
    
    return result


def create_api_key(name, expires_in=100, debug=True):
    """Generate signature for creating a new API key."""
    payload = {
        "name": name,
        "expires_in": expires_in
    }
    print(payload)
    return generate_signature(BASE_PATH, "post", payload, debug)


def delete_api_key(api_key_id, debug=False):
    """Generate signature for deleting an API key."""
    path = f"{BASE_PATH}/{api_key_id}"
    return generate_signature(path, "delete", debug=debug)


def format_curl_command(result, api_key_id=None):
    """Format the result as a curl command for easy testing."""
    headers = result["headers"]
    req_info = result["request_info"]
    
    method = req_info["method"].upper()
    path = req_info["path"]
    
    # Base URL - adjust as needed for production vs staging
    base_url = NYLAS_API_URL
    
    curl_cmd = f"curl --location"
    
    if method == "DELETE":
        curl_cmd += " --request DELETE"
    
    curl_cmd += f" '{base_url}{path}'"
    
    # Add headers
    for key, value in headers.items():
        curl_cmd += f" \\\n--header '{key}: {value}'"
    
    # Add content-type for POST/PUT
    if method in ["POST", "PUT"] and "payload" in req_info:
        curl_cmd += " \\\n--header 'Content-Type: application/json'"
        
        # Add payload
        payload_json = req_info["payload"]
        # Format the payload for better readability
        payload_obj = json.loads(payload_json)
        formatted_payload = json.dumps(payload_obj, indent=4)
        curl_cmd += f" \\\n--data '{formatted_payload}'"
    
    return curl_cmd


def main():
        # Check if required environment variables are set
    if not all([PRIVATE_KEY_BASE64, PRIVATE_KEY_ID, APP_ID]):
        print("Error: Required environment variables are not set.")
        print("Please set the following environment variables:")
        print("  - NYLAS_PRIVATE_KEY_BASE64: Base64-encoded private key")
        print("  - NYLAS_PRIVATE_KEY_ID: Private key ID")
        print("  - NYLAS_APP_ID: Application ID")
        return

    parser = argparse.ArgumentParser(description="Generate Nylas Admin API signatures")

    subparsers = parser.add_subparsers(dest="command", help="Command to execute")
    
    # Create API key command
    create_parser = subparsers.add_parser("create", help="Create a new API key")
    create_parser.add_argument("--name", default="test-api-key", help="Name for the API key")
    create_parser.add_argument("--expires", type=int, default=100, help="Expiration time in seconds")
    
    # Delete API key command
    delete_parser = subparsers.add_parser("delete", help="Delete an API key")
    delete_parser.add_argument("api_key_id", help="ID of the API key to delete")
    
    # Debug flag
    parser.add_argument("--debug", action="store_true", help="Print debug information")
    
    args = parser.parse_args()
    
    if args.command == "create":
        result = create_api_key(args.name, args.expires, True)
        if result:
            print("\n=== API Key Creation Headers ===")
            print(json.dumps(result["headers"], indent=2))
            print("\n=== cURL Command ===")
            print(format_curl_command(result))
    
    elif args.command == "delete":
        result = delete_api_key(args.api_key_id, args.debug)
        if result:
            print("\n=== API Key Deletion Headers ===")
            print(json.dumps(result["headers"], indent=2))
            print("\n=== cURL Command ===")
            print(format_curl_command(result))
    
    else:
        # Default behavior - create an API key with default values
        result = create_api_key("kiran-test-api-key", 100, args.debug)
        if result:
            print(json.dumps(result["request_info"], indent=2))


if __name__ == '__main__':
    main() 
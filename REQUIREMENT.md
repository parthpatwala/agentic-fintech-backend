# Tool & Asset Checklist

## Local Assets to Generate
private_key.pem (An Ed25519 or RSA private key file used by your mock agent to sign tokens).

public_key.pem (The corresponding public key file used by your server to verify signatures).

Here is how you can quickly generate your .pem files using your terminal, depending on your operating system. No need to look up documentation elsewhere:

### For Mac and Linux (Using Terminal)
Open your terminal and run these two commands one after the other. It will generate the cryptographic key pair instantly using the modern, high-performance Ed25519 algorithm standard:

```bash
# 1. Generate an Ed25519 key pair (Press Enter through the prompts to skip the passphrase)
ssh-keygen -t ed25519 -f ./id_ed25519 -N ""

# 2. Rename them to match our project specifications
mv ./id_ed25519 ./private_key.pem
mv ./id_ed25519.pub ./public_key.pem
```

### For Windows (Using PowerShell)
If you are on Windows, standard openssl might not be natively installed. You can use standard Windows ssh-keygen tools instead to output the raw keys:

```bash
PowerShell

# 1. Generate an Ed25519 key pair (press Enter through the prompts to skip passphrase)

ssh-keygen -t ed25519 -f ./id_ed25519 -N ""

# 2. Rename them to .pem format to match your project requirements

Rename-Item ./id_ed25519 private_key.pem
Rename-Item ./id_ed25519.pub public_key.pem
```


## External Accounts & Keys
Stripe Account (Test Mode): You just need the secret API key (sk_test_...) from the developer dashboard.

Google Cloud Platform (GCP) Account: A free-tier account with an active project to host the container later.

 Ngrok Account: A free account to get an authentication token for public tunneling.

## Software Installed on Your Machine
 Cursor IDE

Docker Desktop (To run your app, database, and environment in an isolated container).

Postman (To manually fire JSON payloads at your endpoints and simulate the AI agent).

That is the entire list of ingredients. Once you have these tools installed and keys gathered, your environment is officially ready.
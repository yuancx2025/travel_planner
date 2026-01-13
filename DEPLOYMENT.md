# AWS App Runner Deployment Guide

This guide provides step-by-step instructions for deploying the Travel Planner application to AWS App Runner using Redis for session storage.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Architecture Overview](#architecture-overview)
3. [Quick Start Summary](#quick-start-summary)
4. [Step 1: AWS Account Setup](#step-1-aws-account-setup)
5. [Step 2: Create ECR Repositories](#step-2-create-ecr-repositories)
6. [Step 3: Set Up Redis](#step-3-set-up-redis)
7. [Step 4: Store API Keys in Secrets Manager](#step-4-store-api-keys-in-secrets-manager)
8. [Step 5: Build and Push Docker Images](#step-5-build-and-push-docker-images)
9. [Step 6: Create IAM Roles](#step-6-create-iam-roles)
10. [Step 7: Create App Runner Services](#step-7-create-app-runner-services)
11. [Step 8: Configure Environment Variables](#step-8-configure-environment-variables)
12. [Step 9: Test Deployment](#step-9-test-deployment)
13. [Troubleshooting](#troubleshooting)
14. [Cost Estimation](#cost-estimation)

## Prerequisites

Before starting, ensure you have:

- ✅ AWS Account with appropriate permissions (IAM, ECR, App Runner, Secrets Manager)
- ✅ AWS CLI installed and configured (`aws configure`)
- ✅ Docker installed and running
- ✅ Git (for cloning the repository)
- ✅ Python 3.11+ (for local testing)
- ✅ API Keys ready:
  - Google API Key (Gemini)
  - Google Maps API Key
  - Amadeus API Key and Secret

## Architecture Overview

The deployment consists of:

1. **FastAPI Backend Service** - REST API on port 8000
2. **Streamlit Frontend Service** - Web UI on port 8501
3. **Redis** - Session storage (ElastiCache Serverless or external service)
4. **AWS Secrets Manager** - Secure storage for API keys
5. **ECR (Elastic Container Registry)** - Docker image storage

```
┌─────────────────┐
│   Streamlit     │  Port 8501
│   (Frontend)    │
└────────┬────────┘
         │ HTTP
         ▼
┌─────────────────┐
│   FastAPI       │  Port 8000
│   (Backend)     │
└────────┬────────┘
         │
    ┌────┴────┐
    │ Redis   │  Session Storage
    └─────────┘
```

## Quick Start Summary

For experienced users, here's the high-level flow:

1. Configure AWS CLI → Create ECR repos → Set up Redis → Store secrets → Build/push images → Create IAM roles → Deploy App Runner services → Configure env vars → Test

**Estimated time:** 30-45 minutes for first-time deployment

---

## Step 1: AWS Account Setup

### 1.1 Install AWS CLI

**macOS:**
```bash
brew install awscli
```

**Linux:**
```bash
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip awscliv2.zip
sudo ./aws/install
```

**Windows:**
Download and install from: https://aws.amazon.com/cli/

### 1.2 Configure AWS CLI

```bash
aws configure
```

You'll be prompted for:
- **AWS Access Key ID**: Your AWS access key
- **AWS Secret Access Key**: Your AWS secret key
- **Default region name**: `us-east-1` (or your preferred region)
- **Default output format**: `json`

### 1.3 Verify AWS Access

```bash
aws sts get-caller-identity
```

**Expected output:**
```json
{
    "UserId": "AIDA...",
    "Account": "123456789012",
    "Arn": "arn:aws:iam::123456789012:user/your-username"
}
```

✅ **Checkpoint:** If you see your account ID, AWS CLI is configured correctly.

### 1.4 Set Environment Variables (Optional but Recommended)

```bash
export AWS_REGION=us-east-1
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

# Add to your shell profile (~/.bashrc, ~/.zshrc, etc.)
echo 'export AWS_REGION=us-east-1' >> ~/.zshrc
echo 'export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)' >> ~/.zshrc
```

---

## Step 2: Create ECR Repositories

ECR (Elastic Container Registry) stores your Docker images.

### 2.1 Get Your AWS Account ID

```bash
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
AWS_REGION=${AWS_REGION:-us-east-1}

echo "AWS Account ID: $AWS_ACCOUNT_ID"
echo "AWS Region: $AWS_REGION"
```

### 2.2 Create ECR Repositories

Create repositories for both services:

```bash
# Create FastAPI repository
aws ecr create-repository \
    --repository-name travel-planner-fastapi \
    --region $AWS_REGION \
    --image-scanning-configuration scanOnPush=true \
    --encryption-configuration encryptionType=AES256

# Create Streamlit repository
aws ecr create-repository \
    --repository-name travel-planner-streamlit \
    --region $AWS_REGION \
    --image-scanning-configuration scanOnPush=true \
    --encryption-configuration encryptionType=AES256
```

### 2.3 Verify Repositories

```bash
aws ecr describe-repositories \
    --repository-names travel-planner-fastapi travel-planner-streamlit \
    --region $AWS_REGION
```

**Expected output:** You should see both repositories listed.

✅ **Checkpoint:** Both repositories created successfully.

### 2.4 Login to ECR

You'll need to authenticate Docker with ECR:

```bash
aws ecr get-login-password --region $AWS_REGION | \
    docker login --username AWS --password-stdin \
    $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com
```

**Expected output:** `Login Succeeded`

---

## Step 3: Set Up Redis

You need Redis for session storage. Choose one option:

### Option A: Upstash Redis (Recommended - Easiest)

1. Go to https://upstash.com/
2. Sign up/login
3. Create a new Redis database
4. Choose a region close to your AWS region
5. Copy the **Redis URL** (format: `redis://default:password@host:port`)

**Note:** Upstash provides a public endpoint that works well with App Runner.

### Option B: Redis Cloud

1. Go to https://redis.com/cloud/
2. Create a free account
3. Create a new database
4. Copy the connection URL

### Option C: AWS ElastiCache Serverless (Advanced)

**Note:** This requires VPC configuration and is more complex. Only use if you need AWS-native Redis.

```bash
# First, you need VPC subnets and security groups
# This is a simplified example - adjust subnet-ids and security-group-ids

aws elasticache create-serverless-cache \
    --serverless-cache-name travel-planner-redis \
    --engine redis \
    --region $AWS_REGION \
    --subnet-ids subnet-12345 subnet-67890 \
    --security-group-ids sg-12345

# Wait for creation (5-10 minutes), then get endpoint
aws elasticache describe-serverless-caches \
    --serverless-cache-name travel-planner-redis \
    --region $AWS_REGION \
    --query 'ServerlessCaches[0].Endpoint.Address' \
    --output text
```

**Save your Redis URL** - you'll need it in Step 8.

✅ **Checkpoint:** You have a Redis URL ready (format: `redis://:password@host:port/0`)

---

## Step 4: Store API Keys in Secrets Manager

### 4.1 Create Secrets File

Create a file named `secrets.json` in your project root:

```bash
cd /path/to/travel_planner-main

cat > secrets.json <<EOF
{
  "GOOGLE_API_KEY": "your-actual-google-api-key-here",
  "GOOGLE_MAPS_API_KEY": "your-actual-google-maps-api-key-here",
  "AMADEUS_API_KEY": "your-actual-amadeus-api-key-here",
  "AMADEUS_API_SECRET": "your-actual-amadeus-api-secret-here"
}
EOF
```

**⚠️ Important:** Replace the placeholder values with your actual API keys.

### 4.2 Create Secret in AWS Secrets Manager

```bash
aws secretsmanager create-secret \
    --name travel-planner-api-keys \
    --secret-string file://secrets.json \
    --region $AWS_REGION \
    --description "API keys for Travel Planner application"
```

**Expected output:** You'll see the ARN of the created secret.

### 4.3 Verify Secret Creation

```bash
aws secretsmanager describe-secret \
    --secret-id travel-planner-api-keys \
    --region $AWS_REGION
```

**Expected output:** Secret details including ARN and creation date.

### 4.4 Clean Up Secrets File

```bash
# Remove the local secrets file (it's now in AWS)
rm secrets.json
```

**⚠️ Security:** Never commit `secrets.json` to Git. It should be in `.gitignore`.

✅ **Checkpoint:** Secret created in AWS Secrets Manager.

---

## Step 5: Build and Push Docker Images

### 5.1 Navigate to Project Directory

```bash
cd /path/to/travel_planner-main
```

### 5.2 Ensure You're Logged into ECR

```bash
aws ecr get-login-password --region $AWS_REGION | \
    docker login --username AWS --password-stdin \
    $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com
```

### 5.3 Build and Push FastAPI Image

```bash
# Set image variables
FASTAPI_IMAGE_URI="$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/travel-planner-fastapi:latest"

# Build the image
echo "Building FastAPI Docker image..."
docker build -f Dockerfile.fastapi -t travel-planner-fastapi:latest .

# Tag for ECR
docker tag travel-planner-fastapi:latest $FASTAPI_IMAGE_URI

# Push to ECR
echo "Pushing FastAPI image to ECR..."
docker push $FASTAPI_IMAGE_URI

echo "FastAPI image pushed: $FASTAPI_IMAGE_URI"
```

### 5.4 Build and Push Streamlit Image

```bash
# Set image variables
STREAMLIT_IMAGE_URI="$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/travel-planner-streamlit:latest"

# Build the image
echo "Building Streamlit Docker image..."
docker build -f Dockerfile.streamlit -t travel-planner-streamlit:latest .

# Tag for ECR
docker tag travel-planner-streamlit:latest $STREAMLIT_IMAGE_URI

# Push to ECR
echo "Pushing Streamlit image to ECR..."
docker push $STREAMLIT_IMAGE_URI

echo "Streamlit image pushed: $STREAMLIT_IMAGE_URI"
```

### 5.5 Verify Images in ECR

```bash
# List FastAPI images
aws ecr list-images \
    --repository-name travel-planner-fastapi \
    --region $AWS_REGION

# List Streamlit images
aws ecr list-images \
    --repository-name travel-planner-streamlit \
    --region $AWS_REGION
```

**Expected output:** You should see `latest` tag in both repositories.

✅ **Checkpoint:** Both Docker images are in ECR.

---

## Step 6: Create IAM Roles

App Runner needs IAM roles to access ECR and Secrets Manager.

### 6.1 Create Access Role (for ECR and Secrets Manager)

This role allows App Runner to pull images and read secrets.

```bash
# Create trust policy
cat > /tmp/apprunner-trust-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "build.apprunner.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF

# Create access policy
cat > /tmp/apprunner-access-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "secretsmanager:GetSecretValue",
        "secretsmanager:DescribeSecret"
      ],
      "Resource": "arn:aws:secretsmanager:${AWS_REGION}:${AWS_ACCOUNT_ID}:secret:travel-planner-api-keys-*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "ecr:GetAuthorizationToken",
        "ecr:BatchCheckLayerAvailability",
        "ecr:GetDownloadUrlForLayer",
        "ecr:BatchGetImage"
      ],
      "Resource": "*"
    }
  ]
}
EOF

# Create IAM role
aws iam create-role \
    --role-name AppRunnerAccessRole \
    --assume-role-policy-document file:///tmp/apprunner-trust-policy.json \
    --description "App Runner access role for ECR and Secrets Manager"

# Attach inline policy
aws iam put-role-policy \
    --role-name AppRunnerAccessRole \
    --policy-name ECRAndSecretsAccess \
    --policy-document file:///tmp/apprunner-access-policy.json

# Get role ARN
APP_RUNNER_ACCESS_ROLE_ARN=$(aws iam get-role \
    --role-name AppRunnerAccessRole \
    --query 'Role.Arn' \
    --output text)

echo "App Runner Access Role ARN: $APP_RUNNER_ACCESS_ROLE_ARN"
```

### 6.2 Create Instance Role (for Runtime Access)

This role is used by the running containers to access Secrets Manager.

```bash
# Create trust policy for instance role
cat > /tmp/apprunner-instance-trust-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "tasks.apprunner.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF

# Create instance role
aws iam create-role \
    --role-name AppRunnerInstanceRole \
    --assume-role-policy-document file:///tmp/apprunner-instance-trust-policy.json \
    --description "App Runner instance role for runtime access to Secrets Manager"

# Attach Secrets Manager policy
aws iam put-role-policy \
    --role-name AppRunnerInstanceRole \
    --policy-name SecretsManagerAccess \
    --policy-document file:///tmp/apprunner-access-policy.json

# Get instance role ARN
APP_RUNNER_INSTANCE_ROLE_ARN=$(aws iam get-role \
    --role-name AppRunnerInstanceRole \
    --query 'Role.Arn' \
    --output text)

echo "App Runner Instance Role ARN: $APP_RUNNER_INSTANCE_ROLE_ARN"
```

✅ **Checkpoint:** Both IAM roles created successfully.

---

## Step 7: Create App Runner Services

### 7.1 Set Image URIs

```bash
FASTAPI_IMAGE_URI="$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/travel-planner-fastapi:latest"
STREAMLIT_IMAGE_URI="$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/travel-planner-streamlit:latest"

echo "FastAPI Image: $FASTAPI_IMAGE_URI"
echo "Streamlit Image: $STREAMLIT_IMAGE_URI"
```

### 7.2 Create FastAPI Service

```bash
# Create service configuration
cat > /tmp/apprunner-fastapi-service.json <<EOF
{
  "ServiceName": "travel-planner-fastapi",
  "SourceConfiguration": {
    "ImageRepository": {
      "ImageIdentifier": "${FASTAPI_IMAGE_URI}",
      "ImageConfiguration": {
        "Port": "8000",
        "RuntimeEnvironmentVariables": {
          "PORT": "8000"
        }
      },
      "ImageRepositoryType": "ECR"
    },
    "AutoDeploymentsEnabled": true
  },
  "InstanceConfiguration": {
    "Cpu": "1 vCPU",
    "Memory": "2 GB",
    "InstanceRoleArn": "${APP_RUNNER_INSTANCE_ROLE_ARN}"
  },
  "AccessRole": "${APP_RUNNER_ACCESS_ROLE_ARN}"
}
EOF

# Create the service
aws apprunner create-service \
    --cli-input-json file:///tmp/apprunner-fastapi-service.json \
    --region $AWS_REGION
```

**Expected output:** Service creation initiated. This takes 5-10 minutes.

### 7.3 Wait for FastAPI Service to be Ready

```bash
echo "Waiting for FastAPI service to be created (this may take 5-10 minutes)..."

# Poll until service is running
while true; do
    STATUS=$(aws apprunner list-services \
        --region $AWS_REGION \
        --query "ServiceSummaryList[?ServiceName=='travel-planner-fastapi'].Status" \
        --output text)
    
    if [ "$STATUS" = "RUNNING" ]; then
        echo "FastAPI service is RUNNING!"
        break
    elif [ "$STATUS" = "CREATE_FAILED" ]; then
        echo "FastAPI service creation FAILED. Check logs."
        exit 1
    else
        echo "Status: $STATUS. Waiting..."
        sleep 30
    fi
done

# Get service ARN and URL
FASTAPI_SERVICE_ARN=$(aws apprunner list-services \
    --region $AWS_REGION \
    --query "ServiceSummaryList[?ServiceName=='travel-planner-fastapi'].ServiceArn" \
    --output text)

FASTAPI_URL=$(aws apprunner describe-service \
    --service-arn "$FASTAPI_SERVICE_ARN" \
    --region $AWS_REGION \
    --query 'Service.ServiceUrl' \
    --output text)

echo "FastAPI Service ARN: $FASTAPI_SERVICE_ARN"
echo "FastAPI URL: $FASTAPI_URL"
```

### 7.4 Create Streamlit Service

```bash
# Create service configuration
cat > /tmp/apprunner-streamlit-service.json <<EOF
{
  "ServiceName": "travel-planner-streamlit",
  "SourceConfiguration": {
    "ImageRepository": {
      "ImageIdentifier": "${STREAMLIT_IMAGE_URI}",
      "ImageConfiguration": {
        "Port": "8501",
        "RuntimeEnvironmentVariables": {
          "PORT": "8501"
        }
      },
      "ImageRepositoryType": "ECR"
    },
    "AutoDeploymentsEnabled": true
  },
  "InstanceConfiguration": {
    "Cpu": "1 vCPU",
    "Memory": "2 GB",
    "InstanceRoleArn": "${APP_RUNNER_INSTANCE_ROLE_ARN}"
  },
  "AccessRole": "${APP_RUNNER_ACCESS_ROLE_ARN}"
}
EOF

# Create the service
aws apprunner create-service \
    --cli-input-json file:///tmp/apprunner-streamlit-service.json \
    --region $AWS_REGION
```

### 7.5 Wait for Streamlit Service to be Ready

```bash
echo "Waiting for Streamlit service to be created (this may take 5-10 minutes)..."

# Poll until service is running
while true; do
    STATUS=$(aws apprunner list-services \
        --region $AWS_REGION \
        --query "ServiceSummaryList[?ServiceName=='travel-planner-streamlit'].Status" \
        --output text)
    
    if [ "$STATUS" = "RUNNING" ]; then
        echo "Streamlit service is RUNNING!"
        break
    elif [ "$STATUS" = "CREATE_FAILED" ]; then
        echo "Streamlit service creation FAILED. Check logs."
        exit 1
    else
        echo "Status: $STATUS. Waiting..."
        sleep 30
    fi
done

# Get service ARN and URL
STREAMLIT_SERVICE_ARN=$(aws apprunner list-services \
    --region $AWS_REGION \
    --query "ServiceSummaryList[?ServiceName=='travel-planner-streamlit'].ServiceArn" \
    --output text)

STREAMLIT_URL=$(aws apprunner describe-service \
    --service-arn "$STREAMLIT_SERVICE_ARN" \
    --region $AWS_REGION \
    --query 'Service.ServiceUrl' \
    --output text)

echo "Streamlit Service ARN: $STREAMLIT_SERVICE_ARN"
echo "Streamlit URL: $STREAMLIT_URL"
```

✅ **Checkpoint:** Both services are running. Save the URLs!

---

## Step 8: Configure Environment Variables

Now you need to configure environment variables for both services.

### 8.1 Set Your Redis URL

```bash
# Replace with your actual Redis URL from Step 3
REDIS_URL="redis://:password@your-redis-host:6379/0"
```

### 8.2 Update FastAPI Service with Environment Variables

```bash
# Update FastAPI service
aws apprunner update-service \
    --service-arn "$FASTAPI_SERVICE_ARN" \
    --region $AWS_REGION \
    --source-configuration "{
      \"ImageRepository\": {
        \"ImageIdentifier\": \"${FASTAPI_IMAGE_URI}\",
        \"ImageConfiguration\": {
          \"Port\": \"8000\",
          \"RuntimeEnvironmentVariables\": {
            \"PORT\": \"8000\",
            \"REDIS_URL\": \"${REDIS_URL}\",
            \"AWS_REGION\": \"${AWS_REGION}\",
            \"AWS_SECRETS_MANAGER_SECRET_NAME\": \"travel-planner-api-keys\",
            \"CORS_ORIGINS\": \"${STREAMLIT_URL}\"
          }
        },
        \"ImageRepositoryType\": \"ECR\"
      },
      \"AutoDeploymentsEnabled\": true
    }"
```

**Wait for update to complete** (2-5 minutes):

```bash
echo "Waiting for FastAPI service update to complete..."
sleep 120  # Wait 2 minutes
aws apprunner describe-service \
    --service-arn "$FASTAPI_SERVICE_ARN" \
    --region $AWS_REGION \
    --query 'Service.Status' \
    --output text
```

### 8.3 Update Streamlit Service with Environment Variables

```bash
# Update Streamlit service
aws apprunner update-service \
    --service-arn "$STREAMLIT_SERVICE_ARN" \
    --region $AWS_REGION \
    --source-configuration "{
      \"ImageRepository\": {
        \"ImageIdentifier\": \"${STREAMLIT_IMAGE_URI}\",
        \"ImageConfiguration\": {
          \"Port\": \"8501\",
          \"RuntimeEnvironmentVariables\": {
            \"PORT\": \"8501\",
            \"TRAVEL_PLANNER_API_URL\": \"${FASTAPI_URL}\"
          }
        },
        \"ImageRepositoryType\": \"ECR\"
      },
      \"AutoDeploymentsEnabled\": true
    }"
```

**Wait for update to complete**:

```bash
echo "Waiting for Streamlit service update to complete..."
sleep 120  # Wait 2 minutes
aws apprunner describe-service \
    --service-arn "$STREAMLIT_SERVICE_ARN" \
    --region $AWS_REGION \
    --query 'Service.Status' \
    --output text
```

### 8.4 Alternative: Use AWS Console (Easier for Environment Variables)

If the CLI commands are complex, use the AWS Console:

1. Go to **AWS App Runner Console** → Select your service
2. Click **Configuration** → **Source and deployment** → **Edit**
3. Scroll to **Environment variables**
4. Add the following:

**For FastAPI service:**
- `PORT` = `8000`
- `REDIS_URL` = Your Redis URL
- `AWS_REGION` = `us-east-1` (or your region)
- `AWS_SECRETS_MANAGER_SECRET_NAME` = `travel-planner-api-keys`
- `CORS_ORIGINS` = Your Streamlit URL

**For Streamlit service:**
- `PORT` = `8501`
- `TRAVEL_PLANNER_API_URL` = Your FastAPI URL

5. Click **Save changes** and wait for deployment.

✅ **Checkpoint:** Environment variables configured for both services.

---

## Step 9: Test Deployment

### 9.1 Test FastAPI Health Endpoint

```bash
curl "${FASTAPI_URL}/health"
```

**Expected response:**
```json
{"status": "ok"}
```

### 9.2 Test FastAPI Session Creation

```bash
curl -X POST "${FASTAPI_URL}/sessions" \
    -H "Content-Type: application/json"
```

**Expected response:** JSON with `session_id`, `state`, and `interrupts`.

### 9.3 Test Streamlit Frontend

Open your browser and navigate to:
```
${STREAMLIT_URL}
```

You should see the Travel Planner chat interface.

### 9.4 Verify Redis Connection

Check the App Runner logs:

```bash
# View FastAPI logs
aws logs tail /aws/apprunner/travel-planner-fastapi/service \
    --follow \
    --region $AWS_REGION
```

Look for:
- ✅ `"Connected to Redis for session storage"` (success)
- ❌ `"Failed to connect to Redis"` (failure - check Redis URL)

### 9.5 Test End-to-End Flow

1. Open Streamlit URL in browser
2. Send a test message: "I want to plan a trip to Paris"
3. Verify the chat interface responds
4. Check that session persists after page refresh

✅ **Checkpoint:** All tests passing! Deployment successful.

---

## Troubleshooting

### Issue: Service fails to start

**Check logs:**
```bash
aws logs tail /aws/apprunner/travel-planner-fastapi/service --follow --region $AWS_REGION
```

**Common causes:**
- Missing environment variables
- Redis connection failure (check `REDIS_URL`)
- Invalid API keys in Secrets Manager
- IAM role permissions missing

**Solution:**
1. Verify all environment variables are set correctly
2. Test Redis connection: `redis-cli -u $REDIS_URL ping`
3. Verify secrets in Secrets Manager:
   ```bash
   aws secretsmanager get-secret-value \
       --secret-id travel-planner-api-keys \
       --region $AWS_REGION
   ```

### Issue: CORS errors in browser

**Symptoms:** Browser console shows CORS errors when Streamlit tries to call FastAPI.

**Solution:** Ensure `CORS_ORIGINS` includes your Streamlit URL exactly:

```bash
# Update CORS_ORIGINS
aws apprunner update-service \
    --service-arn "$FASTAPI_SERVICE_ARN" \
    --region $AWS_REGION \
    --source-configuration "{
      \"ImageRepository\": {
        \"ImageIdentifier\": \"${FASTAPI_IMAGE_URI}\",
        \"ImageConfiguration\": {
          \"RuntimeEnvironmentVariables\": {
            \"CORS_ORIGINS\": \"${STREAMLIT_URL}\"
          }
        }
      }
    }"
```

### Issue: Cannot access Secrets Manager

**Symptoms:** Application can't read API keys from Secrets Manager.

**Solution:** Verify IAM role permissions:

```bash
# Check instance role
aws apprunner describe-service \
    --service-arn "$FASTAPI_SERVICE_ARN" \
    --region $AWS_REGION \
    --query 'Service.InstanceConfiguration.InstanceRoleArn'

# Verify policy is attached
aws iam get-role-policy \
    --role-name AppRunnerInstanceRole \
    --policy-name SecretsManagerAccess
```

If policy is missing, re-run Step 6.2.

### Issue: Redis connection timeout

**Symptoms:** Logs show Redis connection errors.

**Solutions:**
1. **Verify Redis URL format:** `redis://:password@host:port/0`
2. **Test Redis connectivity:**
   ```bash
   redis-cli -u "$REDIS_URL" ping
   # Should return: PONG
   ```
3. **For ElastiCache:** Ensure VPC connector is configured in App Runner
4. **For external Redis:** Ensure it's publicly accessible or use VPC peering

### Issue: Docker build fails locally

**Solution:** Build and test locally first:

```bash
# Build FastAPI
docker build -f Dockerfile.fastapi -t test-fastapi .
docker run -p 8000:8000 \
    -e REDIS_URL="redis://localhost:6379/0" \
    -e GOOGLE_API_KEY="test" \
    -e GOOGLE_MAPS_API_KEY="test" \
    test-fastapi

# Build Streamlit
docker build -f Dockerfile.streamlit -t test-streamlit .
docker run -p 8501:8501 \
    -e TRAVEL_PLANNER_API_URL="http://localhost:8000" \
    test-streamlit
```

### Issue: Service stuck in "CREATING" status

**Solution:** Check service events:

```bash
aws apprunner describe-service \
    --service-arn "$FASTAPI_SERVICE_ARN" \
    --region $AWS_REGION \
    --query 'Service.Status' \
    --output text
```

If stuck for >15 minutes, check CloudWatch logs for errors.

---

## Cost Estimation

### App Runner Costs (us-east-1)

- **FastAPI Service:**
  - vCPU: $0.007 per vCPU-hour
  - Memory: $0.0008 per GB-hour
  - Estimated: ~$10-15/month for 1 vCPU, 2 GB (low traffic)

- **Streamlit Service:**
  - Same pricing as FastAPI
  - Estimated: ~$10-15/month

### Additional Services

- **ECR:** $0.10 per GB/month (first 500 MB free)
- **Secrets Manager:** $0.40 per secret/month
- **ElastiCache Serverless:** ~$0.125 per ACU-hour (minimum ~$9/month)
- **External Redis (Upstash):** Free tier available, paid plans start at ~$10/month
- **CloudWatch Logs:** $0.50 per GB ingested

### Total Estimated Monthly Cost

- **Low traffic:** $30-50/month
- **Medium traffic:** $50-100/month
- **High traffic:** $100-200/month

**Note:** Costs vary based on traffic, region, and Redis provider choice.

---

## Next Steps

After successful deployment:

1. **Set up custom domains:**
   ```bash
   aws apprunner associate-custom-domain \
       --service-arn "$STREAMLIT_SERVICE_ARN" \
       --domain-name app.yourdomain.com \
       --region $AWS_REGION
   ```

2. **Configure auto-scaling:**
   - Go to App Runner Console → Your service → Configuration
   - Set min/max instances based on expected traffic
   - Configure based on CPU/memory metrics

3. **Set up monitoring:**
   - CloudWatch alarms for service health
   - Custom metrics for session counts
   - Error rate monitoring

4. **CI/CD Pipeline:**
   - GitHub Actions to build and deploy on push
   - Automated testing before deployment
   - See example workflows in `.github/workflows/`

5. **Backup strategy:**
   - Regular Redis snapshots (if using ElastiCache)
   - Secrets Manager versioning (automatic)

---

## Quick Reference Commands

```bash
# Set variables (run once)
export AWS_REGION=us-east-1
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
export FASTAPI_SERVICE_ARN=$(aws apprunner list-services --region $AWS_REGION --query "ServiceSummaryList[?ServiceName=='travel-planner-fastapi'].ServiceArn" --output text)
export STREAMLIT_SERVICE_ARN=$(aws apprunner list-services --region $AWS_REGION --query "ServiceSummaryList[?ServiceName=='travel-planner-streamlit'].ServiceArn" --output text)

# List all services
aws apprunner list-services --region $AWS_REGION

# Get service status
aws apprunner describe-service --service-arn "$FASTAPI_SERVICE_ARN" --region $AWS_REGION

# View logs
aws logs tail /aws/apprunner/travel-planner-fastapi/service --follow --region $AWS_REGION
aws logs tail /aws/apprunner/travel-planner-streamlit/service --follow --region $AWS_REGION

# Get service URLs
aws apprunner describe-service --service-arn "$FASTAPI_SERVICE_ARN" --region $AWS_REGION --query 'Service.ServiceUrl' --output text
aws apprunner describe-service --service-arn "$STREAMLIT_SERVICE_ARN" --region $AWS_REGION --query 'Service.ServiceUrl' --output text

# Delete services (if needed)
aws apprunner delete-service --service-arn "$FASTAPI_SERVICE_ARN" --region $AWS_REGION
aws apprunner delete-service --service-arn "$STREAMLIT_SERVICE_ARN" --region $AWS_REGION
```

---

## Support

For issues or questions:

1. **Check CloudWatch logs** - Most issues are visible in logs
2. **Review App Runner service events** - Check service status and events
3. **Verify IAM permissions** - Ensure roles have correct policies
4. **Test locally with Docker first** - Debug issues locally before deploying
5. **Check AWS App Runner documentation** - https://docs.aws.amazon.com/apprunner/

---

## Deployment Checklist

Use this checklist to track your deployment progress:

- [ ] AWS CLI installed and configured
- [ ] AWS account access verified
- [ ] ECR repositories created
- [ ] Redis instance set up and URL obtained
- [ ] API keys stored in Secrets Manager
- [ ] Docker images built and pushed to ECR
- [ ] IAM roles created (Access and Instance)
- [ ] FastAPI App Runner service created and running
- [ ] Streamlit App Runner service created and running
- [ ] Environment variables configured for FastAPI
- [ ] Environment variables configured for Streamlit
- [ ] FastAPI health endpoint responding
- [ ] Streamlit frontend accessible
- [ ] End-to-end flow tested successfully

**Congratulations!** 🎉 Your Travel Planner is now deployed on AWS App Runner!

# AWS App Runner Deployment Guide

This guide provides step-by-step instructions for deploying the Travel Planner application to AWS App Runner using Redis for session storage.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Architecture Overview](#architecture-overview)
3. [Step 1: AWS Account Setup](#step-1-aws-account-setup)
4. [Step 2: Create AWS Resources](#step-2-create-aws-resources)
5. [Step 3: Set Up Redis](#step-3-set-up-redis)
6. [Step 4: Store API Keys in Secrets Manager](#step-4-store-api-keys-in-secrets-manager)
7. [Step 5: Build and Push Docker Images](#step-5-build-and-push-docker-images)
8. [Step 6: Create App Runner Services](#step-6-create-app-runner-services)
9. [Step 7: Configure Environment Variables](#step-7-configure-environment-variables)
10. [Step 8: Test Deployment](#step-8-test-deployment)
11. [Troubleshooting](#troubleshooting)
12. [Cost Estimation](#cost-estimation)

## Prerequisites

- AWS Account with appropriate permissions
- AWS CLI installed and configured (`aws configure`)
- Docker installed and running
- Git (for cloning the repository)
- Python 3.11+ (for local testing)
- API Keys:
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

## Step 1: AWS Account Setup

### 1.1 Install and Configure AWS CLI

```bash
# Install AWS CLI (if not already installed)
# macOS:
brew install awscli

# Linux:
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip awscliv2.zip
sudo ./aws/install

# Configure AWS CLI
aws configure
# Enter your AWS Access Key ID
# Enter your AWS Secret Access Key
# Enter default region (e.g., us-east-1)
# Enter default output format (json)
```

### 1.2 Verify AWS Access

```bash
aws sts get-caller-identity
```

You should see your AWS account ID and user ARN.

### 1.3 Set Default Region (Optional)

```bash
export AWS_REGION=us-east-1
# Or add to ~/.bashrc or ~/.zshrc:
echo 'export AWS_REGION=us-east-1' >> ~/.zshrc
```

## Step 2: Create AWS Resources

### 2.1 Run Setup Script

The setup script creates ECR repositories and prepares Secrets Manager:

```bash
cd /path/to/travel_planner-main
./setup-aws.sh
```

This will:
- Create ECR repositories for FastAPI and Streamlit
- Prepare Secrets Manager setup
- Display next steps

### 2.2 Verify ECR Repositories

```bash
aws ecr describe-repositories --region us-east-1
```

You should see two repositories:
- `travel-planner-fastapi`
- `travel-planner-streamlit`

## Step 3: Set Up Redis

You have several options for Redis:

### Option A: AWS ElastiCache Serverless (Recommended for AWS-native)

```bash
# Create ElastiCache Serverless Redis cluster
aws elasticache create-serverless-cache \
    --serverless-cache-name travel-planner-redis \
    --engine redis \
    --region us-east-1 \
    --subnet-ids subnet-12345 subnet-67890 \
    --security-group-ids sg-12345

# Get the endpoint URL (wait a few minutes for creation)
aws elasticache describe-serverless-caches \
    --serverless-cache-name travel-planner-redis \
    --region us-east-1 \
    --query 'ServerlessCaches[0].Endpoint.Address' \
    --output text
```

**Note:** ElastiCache Serverless requires VPC configuration. For App Runner, you'll need to configure VPC connector.

### Option B: External Redis Service (Simpler for App Runner)

Use a managed Redis service that provides a public endpoint:

1. **Redis Cloud** (https://redis.com/cloud/)
2. **Upstash** (https://upstash.com/)
3. **AWS MemoryDB** (alternative to ElastiCache)

After creating the Redis instance, note the connection URL:
```
redis://:password@host:port/0
```

### Option C: Local Redis for Testing

For local testing only:

```bash
docker run -d -p 6379:6379 redis:7-alpine
export REDIS_URL="redis://localhost:6379/0"
```

## Step 4: Store API Keys in Secrets Manager

### 4.1 Create Secrets File

Create a file `secrets.json` with your API keys:

```json
{
  "GOOGLE_API_KEY": "your-actual-google-api-key",
  "GOOGLE_MAPS_API_KEY": "your-actual-google-maps-api-key",
  "AMADEUS_API_KEY": "your-actual-amadeus-api-key",
  "AMADEUS_API_SECRET": "your-actual-amadeus-api-secret"
}
```

### 4.2 Create Secret in AWS Secrets Manager

```bash
aws secretsmanager create-secret \
    --name travel-planner-api-keys \
    --secret-string file://secrets.json \
    --region us-east-1 \
    --description "API keys for Travel Planner application"
```

### 4.3 Verify Secret Creation

```bash
aws secretsmanager describe-secret \
    --secret-id travel-planner-api-keys \
    --region us-east-1
```

**Important:** Never commit `secrets.json` to Git. It's already in `.gitignore`.

## Step 5: Build and Push Docker Images

### 5.1 Run Deployment Script

```bash
cd /path/to/travel_planner-main
./deploy.sh
```

This script will:
1. Log in to ECR
2. Build FastAPI Docker image
3. Push FastAPI image to ECR
4. Build Streamlit Docker image
5. Push Streamlit image to ECR

### 5.2 Verify Images in ECR

```bash
# List FastAPI images
aws ecr list-images \
    --repository-name travel-planner-fastapi \
    --region us-east-1

# List Streamlit images
aws ecr list-images \
    --repository-name travel-planner-streamlit \
    --region us-east-1
```

## Step 6: Create App Runner Services

### 6.1 Get ECR Image URIs

First, get your AWS account ID and construct the image URIs:

```bash
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
AWS_REGION=us-east-1

FASTAPI_IMAGE="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/travel-planner-fastapi:latest"
STREAMLIT_IMAGE="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/travel-planner-streamlit:latest"

echo "FastAPI Image: $FASTAPI_IMAGE"
echo "Streamlit Image: $STREAMLIT_IMAGE"
```

### 6.2 Create IAM Role for App Runner

App Runner needs an IAM role to access Secrets Manager and ECR. Create a role:

```bash
# Create trust policy
cat > apprunner-trust-policy.json <<EOF
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

# Create access policy for Secrets Manager and ECR
cat > apprunner-access-policy.json <<EOF
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
    --role-name AppRunnerServiceRole \
    --assume-role-policy-document file://apprunner-trust-policy.json

# Attach access policy
aws iam put-role-policy \
    --role-name AppRunnerServiceRole \
    --policy-name SecretsManagerAndECRAccess \
    --policy-document file://apprunner-access-policy.json

# Get role ARN
APP_RUNNER_ROLE_ARN=$(aws iam get-role --role-name AppRunnerServiceRole --query 'Role.Arn' --output text)
echo "App Runner Role ARN: $APP_RUNNER_ROLE_ARN"
```

### 6.3 Create FastAPI App Runner Service

Create a service configuration file `apprunner-fastapi-service.json`:

```json
{
  "ServiceName": "travel-planner-fastapi",
  "SourceConfiguration": {
    "ImageRepository": {
      "ImageIdentifier": "${FASTAPI_IMAGE}",
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
    "Memory": "2 GB"
  }
}
```

Create the service:

```bash
# Replace ${FASTAPI_IMAGE} with actual image URI
FASTAPI_IMAGE="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/travel-planner-fastapi:latest"

# Create service configuration
cat > apprunner-fastapi-service.json <<EOF
{
  "ServiceName": "travel-planner-fastapi",
  "SourceConfiguration": {
    "ImageRepository": {
      "ImageIdentifier": "${FASTAPI_IMAGE}",
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
    "Memory": "2 GB"
  },
  "AccessRole": "${APP_RUNNER_ROLE_ARN}"
}
EOF

# Create the service
aws apprunner create-service \
    --cli-input-json file://apprunner-fastapi-service.json \
    --region us-east-1
```

Wait for the service to be created (this takes 5-10 minutes). Get the service ARN:

```bash
FASTAPI_SERVICE_ARN=$(aws apprunner list-services \
    --region us-east-1 \
    --query "ServiceSummaryList[?ServiceName=='travel-planner-fastapi'].ServiceArn" \
    --output text)

echo "FastAPI Service ARN: $FASTAPI_SERVICE_ARN"
```

Get the service URL:

```bash
FASTAPI_URL=$(aws apprunner describe-service \
    --service-arn "$FASTAPI_SERVICE_ARN" \
    --region us-east-1 \
    --query 'Service.ServiceUrl' \
    --output text)

echo "FastAPI URL: $FASTAPI_URL"
```

### 6.4 Create Streamlit App Runner Service

```bash
STREAMLIT_IMAGE="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/travel-planner-streamlit:latest"

cat > apprunner-streamlit-service.json <<EOF
{
  "ServiceName": "travel-planner-streamlit",
  "SourceConfiguration": {
    "ImageRepository": {
      "ImageIdentifier": "${STREAMLIT_IMAGE}",
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
    "Memory": "2 GB"
  },
  "AccessRole": "${APP_RUNNER_ROLE_ARN}"
}
EOF

aws apprunner create-service \
    --cli-input-json file://apprunner-streamlit-service.json \
    --region us-east-1
```

Get the Streamlit service URL:

```bash
STREAMLIT_SERVICE_ARN=$(aws apprunner list-services \
    --region us-east-1 \
    --query "ServiceSummaryList[?ServiceName=='travel-planner-streamlit'].ServiceArn" \
    --output text)

STREAMLIT_URL=$(aws apprunner describe-service \
    --service-arn "$STREAMLIT_SERVICE_ARN" \
    --region us-east-1 \
    --query 'Service.ServiceUrl' \
    --output text)

echo "Streamlit URL: $STREAMLIT_URL"
```

## Step 7: Configure Environment Variables

### 7.1 Update FastAPI Service Configuration

You need to update the FastAPI service with environment variables and secrets:

```bash
# Get current service configuration
aws apprunner describe-service \
    --service-arn "$FASTAPI_SERVICE_ARN" \
    --region us-east-1 > fastapi-service-config.json

# Update with environment variables
# Note: App Runner doesn't support direct Secrets Manager integration via CLI
# You'll need to use the AWS Console or update via service update command

# Update FastAPI service with environment variables
aws apprunner update-service \
    --service-arn "$FASTAPI_SERVICE_ARN" \
    --region us-east-1 \
    --source-configuration '{
      "ImageRepository": {
        "ImageIdentifier": "'"${FASTAPI_IMAGE}"'",
        "ImageConfiguration": {
          "Port": "8000",
          "RuntimeEnvironmentVariables": {
            "PORT": "8000",
            "REDIS_URL": "your-redis-url-here",
            "AWS_REGION": "us-east-1",
            "AWS_SECRETS_MANAGER_SECRET_NAME": "travel-planner-api-keys",
            "CORS_ORIGINS": "'"${STREAMLIT_URL}"'"
          }
        },
        "ImageRepositoryType": "ECR"
      },
      "AutoDeploymentsEnabled": true
    }'
```

**Important:** Replace `your-redis-url-here` with your actual Redis URL.

### 7.2 Update Streamlit Service Configuration

```bash
aws apprunner update-service \
    --service-arn "$STREAMLIT_SERVICE_ARN" \
    --region us-east-1 \
    --source-configuration '{
      "ImageRepository": {
        "ImageIdentifier": "'"${STREAMLIT_IMAGE}"'",
        "ImageConfiguration": {
          "Port": "8501",
          "RuntimeEnvironmentVariables": {
            "PORT": "8501",
            "TRAVEL_PLANNER_API_URL": "'"${FASTAPI_URL}"'"
          }
        },
        "ImageRepositoryType": "ECR"
      },
      "AutoDeploymentsEnabled": true
    }'
```

### 7.3 Alternative: Use AWS Console for Environment Variables

For easier management, use the AWS Console:

1. Go to AWS App Runner Console
2. Select your service
3. Go to "Configuration" → "Source and deployment"
4. Click "Edit"
5. Under "Environment variables", add:
   - For FastAPI:
     - `REDIS_URL`: Your Redis connection URL
     - `AWS_REGION`: `us-east-1`
     - `AWS_SECRETS_MANAGER_SECRET_NAME`: `travel-planner-api-keys`
     - `CORS_ORIGINS`: Your Streamlit service URL
   - For Streamlit:
     - `TRAVEL_PLANNER_API_URL`: Your FastAPI service URL

### 7.4 Grant Secrets Manager Access

The App Runner service role needs permission to read secrets. Update the IAM policy:

```bash
# Update the access policy to include the service execution role
cat > apprunner-execution-policy.json <<EOF
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
    }
  ]
}
EOF

# Get the execution role name (created automatically by App Runner)
EXECUTION_ROLE_NAME=$(aws apprunner describe-service \
    --service-arn "$FASTAPI_SERVICE_ARN" \
    --region us-east-1 \
    --query 'Service.InstanceConfiguration.InstanceRoleArn' \
    --output text | awk -F'/' '{print $NF}')

# Attach policy to execution role
aws iam put-role-policy \
    --role-name "$EXECUTION_ROLE_NAME" \
    --policy-name SecretsManagerAccess \
    --policy-document file://apprunner-execution-policy.json
```

## Step 8: Test Deployment

### 8.1 Test FastAPI Health Endpoint

```bash
curl "${FASTAPI_URL}/health"
```

Expected response:
```json
{"status": "ok"}
```

### 8.2 Test FastAPI Session Creation

```bash
curl -X POST "${FASTAPI_URL}/sessions" \
    -H "Content-Type: application/json"
```

You should receive a session ID and initial state.

### 8.3 Test Streamlit Frontend

Open the Streamlit URL in your browser:
```
${STREAMLIT_URL}
```

You should see the Travel Planner interface.

### 8.4 Verify Redis Connection

Check the App Runner logs to verify Redis connection:

```bash
# Get log stream name
LOG_GROUP="/aws/apprunner/travel-planner-fastapi"

# View recent logs
aws logs tail "$LOG_GROUP" --follow --region us-east-1
```

Look for messages like:
- "Connected to Redis for session storage" (success)
- "Failed to connect to Redis" (failure)

## Troubleshooting

### Issue: Service fails to start

**Check logs:**
```bash
aws logs tail /aws/apprunner/travel-planner-fastapi --follow
```

**Common causes:**
- Missing environment variables
- Redis connection failure
- Invalid API keys

### Issue: CORS errors in browser

**Solution:** Ensure `CORS_ORIGINS` includes your Streamlit URL:
```bash
aws apprunner update-service \
    --service-arn "$FASTAPI_SERVICE_ARN" \
    --source-configuration '{
      "ImageRepository": {
        "ImageConfiguration": {
          "RuntimeEnvironmentVariables": {
            "CORS_ORIGINS": "'"${STREAMLIT_URL}"'"
          }
        }
      }
    }'
```

### Issue: Cannot access Secrets Manager

**Solution:** Verify IAM role permissions:
```bash
# Check execution role
aws apprunner describe-service \
    --service-arn "$FASTAPI_SERVICE_ARN" \
    --query 'Service.InstanceConfiguration.InstanceRoleArn'

# Verify policy is attached
aws iam get-role-policy \
    --role-name <EXECUTION_ROLE_NAME> \
    --policy-name SecretsManagerAccess
```

### Issue: Redis connection timeout

**Solutions:**
1. If using ElastiCache, ensure VPC connector is configured
2. Check security group rules allow App Runner to access Redis
3. Verify Redis URL format: `redis://:password@host:port/0`
4. For external Redis, ensure it's publicly accessible or use VPC peering

### Issue: Docker build fails

**Solution:** Build locally first to debug:
```bash
docker build -f Dockerfile.fastapi -t test-fastapi .
docker run -p 8000:8000 test-fastapi
```

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
- **CloudWatch Logs:** $0.50 per GB ingested

### Total Estimated Monthly Cost

- **Low traffic:** $30-50/month
- **Medium traffic:** $50-100/month
- **High traffic:** $100-200/month

## Next Steps

1. **Set up custom domains:**
   ```bash
   aws apprunner associate-custom-domain \
       --service-arn "$STREAMLIT_SERVICE_ARN" \
       --domain-name api.yourdomain.com
   ```

2. **Configure auto-scaling:**
   - Set min/max instances in App Runner console
   - Configure based on CPU/memory metrics

3. **Set up monitoring:**
   - CloudWatch alarms for service health
   - Custom metrics for session counts
   - Error rate monitoring

4. **CI/CD Pipeline:**
   - GitHub Actions to build and deploy on push
   - Automated testing before deployment

5. **Backup strategy:**
   - Regular Redis snapshots
   - Secrets Manager versioning

## Quick Reference Commands

```bash
# List all services
aws apprunner list-services --region us-east-1

# Get service status
aws apprunner describe-service --service-arn <ARN> --region us-east-1

# View logs
aws logs tail /aws/apprunner/<service-name> --follow

# Update service
aws apprunner update-service --service-arn <ARN> --source-configuration <JSON>

# Delete service
aws apprunner delete-service --service-arn <ARN> --region us-east-1
```

## Support

For issues or questions:
1. Check CloudWatch logs
2. Review App Runner service events
3. Verify IAM permissions
4. Test locally with Docker first


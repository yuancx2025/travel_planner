#!/bin/bash
# AWS Setup Script for Travel Planner
# This script creates ECR repositories and prepares AWS resources

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== Travel Planner AWS Setup ===${NC}\n"

# Get AWS account ID and region
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text 2>/dev/null || echo "")
AWS_REGION=${AWS_REGION:-us-east-1}

if [ -z "$AWS_ACCOUNT_ID" ]; then
    echo -e "${RED}Error: AWS CLI not configured or not authenticated.${NC}"
    echo "Please run: aws configure"
    exit 1
fi

echo "AWS Account ID: $AWS_ACCOUNT_ID"
echo "AWS Region: $AWS_REGION"
echo ""

# Check if repositories already exist
FASTAPI_REPO_EXISTS=$(aws ecr describe-repositories \
    --repository-names travel-planner-fastapi \
    --region $AWS_REGION \
    --query 'repositories[0].repositoryName' \
    --output text 2>/dev/null || echo "")

STREAMLIT_REPO_EXISTS=$(aws ecr describe-repositories \
    --repository-names travel-planner-streamlit \
    --region $AWS_REGION \
    --query 'repositories[0].repositoryName' \
    --output text 2>/dev/null || echo "")

# Create FastAPI repository
if [ "$FASTAPI_REPO_EXISTS" != "travel-planner-fastapi" ]; then
    echo -e "${YELLOW}Creating ECR repository for FastAPI...${NC}"
    aws ecr create-repository \
        --repository-name travel-planner-fastapi \
        --region $AWS_REGION \
        --image-scanning-configuration scanOnPush=true \
        --encryption-configuration encryptionType=AES256 \
        > /dev/null
    echo -e "${GREEN}✓ FastAPI repository created${NC}"
else
    echo -e "${GREEN}✓ FastAPI repository already exists${NC}"
fi

# Create Streamlit repository
if [ "$STREAMLIT_REPO_EXISTS" != "travel-planner-streamlit" ]; then
    echo -e "${YELLOW}Creating ECR repository for Streamlit...${NC}"
    aws ecr create-repository \
        --repository-name travel-planner-streamlit \
        --region $AWS_REGION \
        --image-scanning-configuration scanOnPush=true \
        --encryption-configuration encryptionType=AES256 \
        > /dev/null
    echo -e "${GREEN}✓ Streamlit repository created${NC}"
else
    echo -e "${GREEN}✓ Streamlit repository already exists${NC}"
fi

# Get repository URIs
FASTAPI_REPO_URI="$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/travel-planner-fastapi"
STREAMLIT_REPO_URI="$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/travel-planner-streamlit"

echo ""
echo -e "${GREEN}=== Setup Complete ===${NC}"
echo ""
echo "ECR Repositories:"
echo "  FastAPI:  $FASTAPI_REPO_URI"
echo "  Streamlit: $STREAMLIT_REPO_URI"
echo ""
echo "Next steps:"
echo "1. Set up Redis (see Step 3 in DEPLOYMENT.md)"
echo "2. Store API keys in Secrets Manager (see Step 4 in DEPLOYMENT.md)"
echo "3. Build and push Docker images (see Step 5 in DEPLOYMENT.md)"
echo "   Or run: ./deploy.sh"
echo ""


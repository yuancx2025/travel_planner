#!/bin/bash
# Docker Build and Push Script for Travel Planner
# This script builds Docker images and pushes them to ECR

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== Travel Planner Docker Deployment ===${NC}\n"

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

# Set image URIs
FASTAPI_IMAGE_URI="$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/travel-planner-fastapi:latest"
STREAMLIT_IMAGE_URI="$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/travel-planner-streamlit:latest"

# Login to ECR
echo -e "${YELLOW}Logging in to ECR...${NC}"
aws ecr get-login-password --region $AWS_REGION | \
    docker login --username AWS --password-stdin \
    $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com
echo -e "${GREEN}✓ ECR login successful${NC}\n"

# Build and push FastAPI image
echo -e "${YELLOW}Building FastAPI Docker image...${NC}"
docker build -f Dockerfile.fastapi -t travel-planner-fastapi:latest .

echo -e "${YELLOW}Tagging FastAPI image...${NC}"
docker tag travel-planner-fastapi:latest $FASTAPI_IMAGE_URI

echo -e "${YELLOW}Pushing FastAPI image to ECR...${NC}"
docker push $FASTAPI_IMAGE_URI
echo -e "${GREEN}✓ FastAPI image pushed: $FASTAPI_IMAGE_URI${NC}\n"

# Build and push Streamlit image
echo -e "${YELLOW}Building Streamlit Docker image...${NC}"
docker build -f Dockerfile.streamlit -t travel-planner-streamlit:latest .

echo -e "${YELLOW}Tagging Streamlit image...${NC}"
docker tag travel-planner-streamlit:latest $STREAMLIT_IMAGE_URI

echo -e "${YELLOW}Pushing Streamlit image to ECR...${NC}"
docker push $STREAMLIT_IMAGE_URI
echo -e "${GREEN}✓ Streamlit image pushed: $STREAMLIT_IMAGE_URI${NC}\n"

echo -e "${GREEN}=== Deployment Complete ===${NC}"
echo ""
echo "Images pushed to ECR:"
echo "  FastAPI:  $FASTAPI_IMAGE_URI"
echo "  Streamlit: $STREAMLIT_IMAGE_URI"
echo ""
echo "Next steps:"
echo "1. Create IAM roles (see Step 6 in DEPLOYMENT.md)"
echo "2. Create App Runner services (see Step 7 in DEPLOYMENT.md)"
echo "3. Configure environment variables (see Step 8 in DEPLOYMENT.md)"
echo ""


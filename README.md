# Aircraft Monitoring System - AWS Deployment

This repository contains a FastAPI application for aircraft monitoring, configured for deployment on AWS using containers and AWS CDK.

## Prerequisites

1. AWS CLI installed and configured
2. Docker installed
3. Node.js and npm installed
4. AWS CDK CLI installed (`npm install -g aws-cdk`)

## Deployment Steps

1. First, install the CDK dependencies:
```bash
cd cdk
npm install
```

2. Configure your secrets in AWS Secrets Manager:
   - Create a secret named 'SlackWebhookUrl' with your Slack webhook URL
   - Create a secret named 'RapidApiKey' with your RapidAPI key

3. Build and deploy the CDK stack:
```bash
cd cdk
cdk deploy
```

4. After deployment, the CDK will output your Load Balancer DNS name. Use this URL to configure your Slack app's Event Subscription URL.

## Architecture

The application is deployed with the following AWS services:

- **ECS Fargate**: Runs the containerized FastAPI application
- **Application Load Balancer**: Handles incoming HTTP traffic
- **DynamoDB**: Stores aircraft tracking state
- **AWS Secrets Manager**: Securely stores API keys and webhooks
- **VPC**: Provides networking infrastructure

## Development

To run the application locally:

1. Install Python dependencies:
```bash
pip install -r requirements.txt
```

2. Set up environment variables:
```bash
export SLACK_WEBHOOK_URL=your_webhook_url
export RAPIDAPI_KEY=your_api_key
```

3. Run the FastAPI application:
```bash
uvicorn aircraftmon_fastapi:app --host 0.0.0.0 --port 4200
```

## Security Notes

- The application uses AWS Secrets Manager for sensitive values
- IAM roles are configured with least privilege access
- All traffic is routed through an Application Load Balancer
- The container runs in a private subnet with NAT Gateway for outbound traffic

## Monitoring

- Use AWS CloudWatch to monitor the ECS tasks
- Container logs are automatically sent to CloudWatch Logs
- DynamoDB metrics are available in CloudWatch Metrics
- ALB metrics provide insight into HTTP traffic patterns 
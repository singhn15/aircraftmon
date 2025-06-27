# Aircraft Monitoring System - AWS Deployment

This repository contains a FastAPI application for aircraft monitoring, configured for deployment on AWS using containers and AWS CDK.

## Prerequisites

1. python3.9
2. see requirements.txt
3. awscli installed and configured

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
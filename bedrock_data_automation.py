import os
import json
import time
import boto3

AWS_REGION = os.getenv('AWS_REGION', '<REGION>')
BUCKET_NAME = os.getenv('AWS_BUCKET_NAME', '<BUCKET>')
INPUT_PATH = os.getenv('AWS_INPUT_PATH', 'BDA/Input')
OUTPUT_PATH = os.getenv('AWS_OUTPUT_PATH', 'BDA/Output')
PROJECT_ID = os.getenv('AWS_PROJECT_ID', '<PROJECT_ID>')
BLUEPRINT_NAME = os.getenv('AWS_BLUEPRINT_NAME', 'US-Driver-License-demo')

BLUEPRINT_FIELDS = [
    'NAME_DETAILS/FIRST_NAME',
    'NAME_DETAILS/MIDDLE_NAME',
    'NAME_DETAILS/LAST_NAME',
    'DATE_OF_BIRTH',
    'DATE_OF_ISSUE',
    'EXPIRATION_DATE'
]

def process_with_bedrock_data_automation(local_file_path):
    """
    Uploads the file to S3, invokes Bedrock Data Automation, waits for completion, and parses the result.
    Returns a dict suitable for Invoice.model_validate().
    """
    s3 = boto3.client('s3', region_name=AWS_REGION)
    bda = boto3.client('bedrock-data-automation-runtime', region_name=AWS_REGION)
    sts = boto3.client('sts')
    
    aws_account_id = sts.get_caller_identity().get('Account')
    file_name = os.path.basename(local_file_path)
    input_s3_uri = f"s3://{BUCKET_NAME}/{INPUT_PATH}/{file_name}"
    output_s3_uri = f"s3://{BUCKET_NAME}/{OUTPUT_PATH}"
    data_automation_arn = f"arn:aws:bedrock:{AWS_REGION}:{aws_account_id}:data-automation-project/{PROJECT_ID}"

    # Upload file to S3
    s3.upload_file(local_file_path, BUCKET_NAME, f"{INPUT_PATH}/{file_name}")

    params = {
        'inputConfiguration': {
            's3Uri': input_s3_uri
        },
        'outputConfiguration': {
            's3Uri': output_s3_uri
        },
        'dataAutomationConfiguration': {
            'dataAutomationProjectArn': data_automation_arn
        },
        'dataAutomationProfileArn': f"arn:aws:bedrock:{AWS_REGION}:{aws_account_id}:data-automation-profile/us.data-automation-v1"
    }
    response = bda.invoke_data_automation_async(**params)
    invocation_arn = response['invocationArn']

    # Wait for completion
    while True:
        status_response = bda.get_data_automation_status(invocationArn=invocation_arn)
        status = status_response['status']
        if status not in ['Created', 'InProgress']:
            break
        time.sleep(2)

    if status_response['status'] != 'Success':
        raise RuntimeError(f"Bedrock Data Automation failed: {status_response['status']}")

    # Retrieve result metadata from S3
    job_metadata_s3_uri = status_response['outputConfiguration']['s3Uri']
    bucket = job_metadata_s3_uri.split('/')[2]
    key = '/'.join(job_metadata_s3_uri.split('/')[3:])
    object_content = s3.get_object(Bucket=bucket, Key=key)['Body'].read()
    job_metadata = json.loads(object_content)

    # Parse the first segment and standard output (customize as needed)
    segment = job_metadata['output_metadata'][0]
    segment_metadata = segment['segment_metadata'][0]
    standard_output_path = segment_metadata['standard_output_path']
    std_bucket = standard_output_path.split('/')[2]
    std_key = '/'.join(standard_output_path.split('/')[3:])
    std_content = s3.get_object(Bucket=std_bucket, Key=std_key)['Body'].read()
    standard_output_result = json.loads(std_content)

    # Map to Invoice fields (customize mapping as needed)
    invoice_dict = {
        'invoice_number': standard_output_result.get('document_id'),
        'invoice_date': standard_output_result.get('date'),
        'seller': {
            'name': standard_output_result.get('issuer_name'),
            'address': standard_output_result.get('issuer_address'),
            'gstin': standard_output_result.get('issuer_gstin'),
            'contact_details': standard_output_result.get('issuer_contact'),
        },
        'buyer': {
            'name': standard_output_result.get('buyer_name'),
            'address': standard_output_result.get('buyer_address'),
            'gstin': standard_output_result.get('buyer_gstin'),
            'contact_details': standard_output_result.get('buyer_contact'),
        },
        # Add more mappings as needed
    }
    return invoice_dict

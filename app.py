import os
import json
import base64
import tempfile
import traceback
import os
import re
from mimetypes import guess_type
from typing import List, Optional
from pydantic import BaseModel
from dotenv import load_dotenv
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import DocumentContentFormat
from azure.core.credentials import AzureKeyCredential
from openai import AzureOpenAI
from pdf2image import convert_from_path
from flask import Flask, request, render_template, flash, jsonify, send_file, redirect, url_for
from werkzeug.utils import secure_filename
from azure.ai.inference import ChatCompletionsClient
import boto3  # Added for Amazon Bedrock integration
from botocore.exceptions import BotoCoreError, ClientError

# Load environment variables from .env file
load_dotenv()

from typing import List, Optional, Dict, Union, Any
from pydantic import BaseModel, Field
from datetime import date, datetime


class SellerInfo(BaseModel):
    """Information about the seller/vendor"""
    name: Optional[str] = Field(None, description="Legal name of the seller")
    address: Optional[str] = Field(None, description="Complete address of the seller")
    gstin: Optional[str] = Field(None, description="GST Identification Number of the seller")
    pan: Optional[str] = Field(None, description="Permanent Account Number of the seller")
    contact_details: Optional[str] = Field(None, description="Contact information including phone, email, etc.")


class BuyerInfo(BaseModel):
    """Information about the buyer/customer"""
    name: Optional[str] = Field(None, description="Legal name of the buyer")
    address: Optional[str] = Field(None, description="Complete address of the buyer")
    gstin: Optional[str] = Field(None, description="GST Identification Number of the buyer")
    pan: Optional[str] = Field(None, description="Permanent Account Number of the buyer")
    contact_details: Optional[str] = Field(None, description="Contact information including phone, email, etc.")


class LineItem(BaseModel):
    """Details of a single line item in the invoice"""
    description: Optional[str] = Field(None, description="Description of the product or service")
    hsn_sac: Optional[str] = Field(None, description="HSN (Harmonized System of Nomenclature) or SAC (Services Accounting Code)")
    quantity: Optional[float] = Field(None, description="Quantity of the item")
    unit: Optional[str] = Field(None, description="Unit of measurement (e.g., PCS, KG, HRS)")
    unit_price: Optional[float] = Field(None, description="Price per unit")
    tax_percentage: Optional[float] = Field(None, description="Tax percentage applied to this item")
    tax_amount: Optional[float] = Field(None, description="Tax amount for this item")
    amount: Optional[float] = Field(None, description="Total amount for the line item (typically quantity × unit_price)")


class TaxDetail(BaseModel):
    """Details of a tax component"""
    tax_type: Optional[str] = Field(None, description="Type of tax (e.g., CGST, SGST, IGST)")
    rate: Optional[float] = Field(None, description="Tax rate as a percentage")
    amount: Optional[float] = Field(None, description="Amount of tax")


class BankDetails(BaseModel):
    """Banking information for payment"""
    bank_name: Optional[str] = Field(None, description="Name of the bank")
    account_number: Optional[str] = Field(None, description="Bank account number")
    ifsc_code: Optional[str] = Field(None, description="IFSC (Indian Financial System Code)")
    branch: Optional[str] = Field(None, description="Bank branch location")


class ShippingDetails(BaseModel):
    """Information about shipping or delivery"""
    shipped_to: Optional[str] = Field(None, description="Name of the recipient")
    ship_to_address: Optional[str] = Field(None, description="Shipping address")
    place_of_supply: Optional[str] = Field(None, description="State code or name for place of supply")
    transporter: Optional[str] = Field(None, description="Name of the transporter")
    vehicle_number: Optional[str] = Field(None, description="Vehicle registration number")
    dispatch_date: Optional[str] = Field(None, description="Date of dispatch")


class Invoice(BaseModel):
    """Complete invoice data model"""
    # Basic invoice information
    invoice_number: Optional[str] = Field(None, description="Unique identifier for the invoice")
    invoice_date: Optional[str] = Field(None, description="Date when the invoice was issued (DD/MM/YYYY format)")
    due_date: Optional[str] = Field(None, description="Date by which payment is due (DD/MM/YYYY format)")
    payment_terms: Optional[str] = Field(None, description="Terms of payment (e.g., '30 days', 'Net 15', 'Immediate')")
    currency: Optional[str] = Field(None, description="Currency code or symbol (e.g., INR, USD, EUR)")
    
    # Parties information
    seller: Optional[SellerInfo] = Field(None, description="Information about the seller/vendor")
    buyer: Optional[BuyerInfo] = Field(None, description="Information about the buyer/customer")
    
    # Line items and financial information
    items: List[LineItem] = Field(default_factory=list, description="Line items in the invoice")
    subtotal: Optional[float] = Field(None, description="Total amount before taxes in the invoice currency")
    tax_details: List[TaxDetail] = Field(default_factory=list, description="Breakdown of taxes applied")
    total_tax_amount: Optional[float] = Field(None, description="Sum of all taxes in the invoice currency")
    total_amount: Optional[float] = Field(None, description="Final invoice amount including taxes in the invoice currency")
    amount_in_words: Optional[str] = Field(None, description="Total amount expressed in words including currency")
    
    # Reference information
    po_number: Optional[str] = Field(None, description="Purchase Order number reference")
    shipping_details: Optional[ShippingDetails] = Field(None, description="Information about shipping or delivery")
    bank_details: Optional[BankDetails] = Field(None, description="Banking information for payment")
    
    # GST-specific information
    irn: Optional[str] = Field(None, description="Invoice Reference Number for e-invoicing")
    ack_number: Optional[str] = Field(None, description="Acknowledgement number for e-invoicing")
    place_of_supply: Optional[str] = Field(None, description="State code or name for place of supply")
    reverse_charge: Optional[bool] = Field(None, description="Whether reverse charge mechanism is applicable")
    
    # Additional information
    notes: Optional[str] = Field(None, description="Additional notes or terms and conditions")

    class Config:
        json_schema_extra = {
            "example": {
                "invoice_number": "2425MR1058",
                "invoice_date": "17/12/2024",
                "due_date": "31/01/2025",
                "payment_terms": "45 Days",
                "seller": {
                    "name": "SAFEX FIRE SERVICES LTD.",
                    "address": "Fact: PLOT NO.13,14,15,OPP.BIDCO, TAL:PALGHAR, DIST.PALGHAR, MAHARASHTRA - 401404",
                    "gstin": "27AAECS7539M1ZP",
                    "contact_details": "CONTACT NO.02525-251482,252686 E-Mail: palghar@safexfire.com"
                },
                "buyer": {
                    "name": "TATA CONSULTANCY SERVICES LTD (MALAD)",
                    "address": "1FL WING A, 2 & 3FL WING B,7FL WING A, 8FL WING A & B,TRIL IT4,INFINIY IT PARK",
                    "gstin": "27AAACR4849R1ZL",
                    "contact_details": "Tel No. : 022-63718493"
                },
                "items": [
                    {
                        "description": "ANNUAL MAINTANACE FOR FIRE EXT SERVICE MONTH - NOVEMBER 2024",
                        "hsn_sac": "998719",
                        "quantity": 433,
                        "unit": "Nos",
                        "rate": 16.00,
                        "amount": 6928.00
                    }
                ],
                "subtotal": 6928.00,
                "tax_details": [
                    {
                        "tax_type": "CGST",
                        "rate": 9,
                        "amount": 623.52
                    },
                    {
                        "tax_type": "SGST",
                        "rate": 9,
                        "amount": 623.52
                    }
                ],
                "total_tax_amount": 1247.04,
                "total_amount": 8175.00,
                "amount_in_words": "Eight Thousand One Hundred Seventy Five Only",
                "irn": "bd13c19a0060a19ed820359c025761eb778929c354829ba08e1ebd1e429b75"
            }
        }


def convert_pdf_to_image(pdf_path: str, output_dir: str) -> str:
    """Convert first page of PDF to image and save it in the output directory"""
    # Convert PDF to image (first page only)
    images = convert_from_path(pdf_path, first_page=1, last_page=1)
    if not images:
        raise ValueError(f"Could not convert PDF to image: {pdf_path}")
    
    # Save the first page image
    image_path = os.path.join(output_dir, "page_1.jpg")
    images[0].save(image_path, "JPEG")
    return image_path

def local_image_to_data_url(image_path: str) -> str:
    mime_type, _ = guess_type(image_path)
    if mime_type is None:
        mime_type = 'application/octet-stream'
    
    with open(image_path, "rb") as image_file:
        base64_encoded_data = base64.b64encode(image_file.read()).decode('utf-8')
    
    return f"data:{mime_type};base64,{base64_encoded_data}"

def analyze_and_parse_invoice(
    doc_intelligence_endpoint: str,
    doc_intelligence_key: str,
    openai_endpoint: str,
    openai_key: str,
    deployment_name: str,
    input_file: str,
    processing_method: str = "bedrock_claude_sonnet"
):
    # --- Amazon Bedrock Claude Sonnet integration variables ---
    # Set these in your .env or environment:
    # AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION, BEDROCK_CLAUDE_MODEL_ID
    AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
    BEDROCK_CLAUDE_MODEL_ID = os.getenv("BEDROCK_CLAUDE_MODEL_ID", "anthropic.claude-3-sonnet-20240229-v1:0")

    # Check if we have a cached result for this file and processing method
    cached_result = get_cached_result(input_file, processing_method)
    if cached_result:
        return cached_result
    # Initialize OpenAI client (needed for both methods)
    openai_client = AzureOpenAI(
        azure_endpoint=openai_endpoint,
        api_key=openai_key,
        api_version="2024-08-01-preview"
    )
    
    # Create a temporary directory that will persist through the function
    temp_dir = tempfile.mkdtemp()
    try:
        # If input is PDF, convert to image first
        if input_file.lower().endswith('.pdf'):
            image_path = convert_pdf_to_image(input_file, temp_dir)
        else:
            image_path = input_file
            
        # Process based on selected method
        if processing_method == "gpt_only":
            # Use GPT-4o with image directly
            print(f"Using GPT-4o with direct image processing")
            with open(image_path, "rb") as img_file:
                # Convert the image to base64
                base64_image = base64.b64encode(img_file.read()).decode("utf-8")
        else: 
            PROCESSING_METHODS = [
                "di_gpt_image",  # Document Intelligence + GPT-4o with image
                "di_gpt_no_image",  # Document Intelligence + GPT-4o without image
                "di_phi",  # Document Intelligence + Microsoft Phi-3
                "gpt_only",  # GPT-4o with image only
                "bedrock_claude_sonnet",  # Amazon Bedrock Claude Sonnet
                "bedrock_data_automation",  # Amazon Bedrock Data Automation
                "textract_claude"  # Amazon Textract + Claude
            ]
            # Initialize Document Intelligence client
            doc_client = DocumentIntelligenceClient(
                endpoint=doc_intelligence_endpoint,
                credential=AzureKeyCredential(doc_intelligence_key)
            )
            print(f"Using Document Intelligence with processing method: {processing_method}")
            
            # Initialize the Phi client if needed
            if processing_method == 'di_phi':
                inference_client = ChatCompletionsClient(
                    endpoint=PHI_DI_ENDPOINT,
                    credential=AzureKeyCredential(PHI_DI_KEY),
                )

        # Prepare the system prompt for both methods
        system_prompt = """You are an AI assistant specialized in extracting invoice data.
Extract complete and accurate information from the invoice document.

Extract the following information:
- Basic invoice details (number, date, due date, payment terms)
- Currency used in the invoice (e.g., INR, USD, EUR) - extract this from the document or from any 'amount in words' text
- Seller and buyer information (name, address, GSTIN, contact details)
- Line items with descriptions, quantities, unit prices, tax percentages, tax amounts, and total amounts
- Tax details (CGST, SGST, IGST rates and amounts)
- Total amounts, bank details, and any reference numbers

For line items, make sure to:
1. Extract unit_price (price per unit) correctly
2. Include tax_percentage and tax_amount when available
3. Ensure amount reflects the total for each line item

Format your response with appropriate fields. Format monetary values as numbers without currency symbols, but be sure to extract and include the currency code/symbol in the 'currency' field.
If the currency appears in 'amount in words' (e.g., 'INR Thirty-Four Thousand'), extract it for the currency field.
Ensure all data is extracted accurately."""
        
        # For methods that need image data
        if processing_method in ["di_gpt_image", "gpt_only"]:
            if processing_method == "gpt_only":
                # For gpt_only, we already have base64_image
                image_data_url = f"data:image/jpeg;base64,{base64_image}"
            else:
                # For di_gpt_image, convert image to data URL
                image_data_url = local_image_to_data_url(image_path)
        
        # Read the document for Document Intelligence (for DI methods)
        if processing_method in ["di_gpt_image", "di_gpt_no_image", "di_phi"]:
            with open(input_file, 'rb') as f:
                document_data = f.read()
            
            # Get layout analysis with markdown
            poller = doc_client.begin_analyze_document(
                'prebuilt-layout',
                document_data,
                output_content_format=DocumentContentFormat.MARKDOWN
            )
            doc_result = poller.result()
        
        # Process based on the selected method
        if processing_method == "gpt_only":
            # Call GPT-4o with just the image
            print("Sending image to GPT-4o for direct processing")
            response = openai_client.beta.chat.completions.parse(
                model=deployment_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": [
                        {
                            "type": "text",
                            "text": "Please extract the information from this invoice image according to the model structure."
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": image_data_url
                            }
                        }
                    ]}
                ],
                response_format=Invoice,
            )
        elif processing_method == "di_gpt_image":
            # Call GPT-4o with Document Intelligence results AND image
            print("Sending Document Intelligence results WITH image to GPT-4o")
            # Modified prompt for DI+GPT method
            di_system_prompt = system_prompt + "\n\nThe document has already been processed by Document Intelligence, and the extracted text is provided to you along with the original image."
            
            response = openai_client.beta.chat.completions.parse(
                model=deployment_name,
                messages=[
                    {"role": "system", "content": di_system_prompt},
                    {"role": "user", "content": [
                        {
                            "type": "text",
                            "text": f"Here is the extracted text from the invoice:\n\n{doc_result.content}\n\nPlease extract the information according to the model structure."
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": image_data_url
                            }
                        }
                    ]}
                ],
                response_format=Invoice,
            )
        elif processing_method == 'di_phi':
            # Call DI+Phi with the document
            print("Sending document to DI+Phi")
            # Prepare the system prompt and user content for Phi
            system_prompt = "You are an AI assistant that extracts data from documents and returns them as structured JSON objects."
            user_content = []
            user_text_prompt = f"""ou are an AI assistant specialized in extracting invoice data.
Extract complete and accurate information from the invoice document.

Extract the following information:
- Basic invoice details (number, date, due date, payment terms)
- Currency used in the invoice (e.g., INR, USD, EUR) - extract this from the document or from any 'amount in words' text
- Seller and buyer information (name, address, GSTIN, contact details)
- Line items with descriptions, quantities, unit prices, tax percentages, tax amounts, and total amounts
- Tax details (CGST, SGST, IGST rates and amounts)
- Total amounts, bank details, and any reference numbers

For line items, make sure to:
1. Extract unit_price (price per unit) correctly
2. Include tax_percentage and tax_amount when available
3. Ensure amount reflects the total for each line item

Format your response with appropriate fields. Format monetary values as numbers without currency symbols, but be sure to extract and include the currency code/symbol in the 'currency' field.
If the currency appears in 'amount in words' (e.g., 'INR Thirty-Four Thousand'), extract it for the currency field.
Ensure all data is extracted accurately.
- Strictly use the following JSON schema: {json.dumps(Invoice.model_json_schema())}
- ONLY return the JSON object. DO NOT return as a JSON markdown code block. DO NOT include any other detail in your response."""

            user_content.append({
                "type": "text",
                "text": user_text_prompt
            })

            # Use the doc_result.content as the markdown text for DI+Phi
            user_content.append({
                "type": "text",
                "text": doc_result.content
            })
            
            response = inference_client.complete(
                messages=[
                    {
                        "role": "system",
                        "content": system_prompt,
                    },
                    {
                        "role": "user",
                        "content": user_content
                    }
                ],
                temperature=0.1,
                top_p=0.1
            )
        elif processing_method == "bedrock_claude_sonnet":
            # Amazon Bedrock Claude Sonnet integration
            print("Processing with Amazon Bedrock Claude Sonnet...")
            # Get the Claude model ID from environment variables
            AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
            CLAUDE_MODEL_ID = os.getenv("BEDROCK_CLAUDE_MODEL_ID", "arn:aws:bedrock:us-east-1:302263040839:inference-profile/us.anthropic.claude-3-5-sonnet-20240620-v1:0")
            try:
                # Prepare image: if PDF, convert to image
                if input_file.lower().endswith('.pdf'):
                    temp_img_path = convert_pdf_to_image(input_file, temp_dir)
                    image_path = temp_img_path
                else:
                    image_path = input_file
                    
                # Read image as base64
                with open(image_path, "rb") as img_file:
                    img_bytes = img_file.read()
                    img_b64 = base64.b64encode(img_bytes).decode("utf-8")
                    
                # System message for Claude with schema
                system_message = """You are an expert invoice parser. Extract all relevant invoice fields in structured JSON format from the invoice image. Respond ONLY with a JSON object matching the invoice schema, no extra text. 

Follow this exact schema structure for your JSON response:

{
  "invoice_number": "string",
  "invoice_date": "string (YYYY-MM-DD)",
  "due_date": "string (YYYY-MM-DD)",
  "payment_terms": "string",
  "currency": "string",
  "seller": {
    "name": "string",
    "address": "string",
    "gstin": "string",
    "pan": "string",
    "contact_details": "string"
  },
  "buyer": {
    "name": "string",
    "address": "string",
    "gstin": "string",
    "pan": "string",
    "contact_details": "string"
  },
  "line_items": [
    {
      "description": "string",
      "hsn_sac": "string",
      "quantity": number,
      "unit": "string",
      "unit_price": number,
      "tax_percentage": number,
      "tax_amount": number,
      "amount": number
    }
  ],
  "subtotal": number,
  "tax_details": [
    {
      "tax_type": "string (e.g., CGST, SGST, IGST)",
      "rate": number,
      "amount": number
    }
  ],
  "total_tax_amount": number,
  "total_amount": number,
  "amount_in_words": "string",
  "po_number": "string",
  "shipping_details": {
    "shipped_to": "string",
    "ship_to_address": "string",
    "place_of_supply": "string",
    "transporter": "string",
    "vehicle_number": "string",
    "dispatch_date": "string"
  },
  "bank_details": {
    "bank_name": "string",
    "account_number": "string",
    "ifsc_code": "string",
    "branch": "string"
  },
  "irn": "string",
  "ack_number": "string",
  "place_of_supply": "string",
  "reverse_charge": boolean,
  "notes": "string"
}

Important notes:
1. All fields are optional. If a field is not found in the document, omit it from the JSON rather than including it with a null or empty value.
2. Always include the tax_details array even if empty.
3. CRITICAL: You MUST use the key 'line_items' (not 'items') for the array of invoice line items as shown in the schema. The UI expects this exact field name."""
                
                # Prepare multimodal message with the image
                message_content = [
                    {
                        "type": "text",
                        "text": "Please extract the information from this invoice image according to the model structure."
                    },
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": img_b64
                        }
                    }
                ]
                
                # Call Bedrock with the proper Messages API format
                bedrock = boto3.client("bedrock-runtime", region_name=AWS_REGION)
                response = bedrock.invoke_model(
                    modelId=CLAUDE_MODEL_ID,
                    body=json.dumps({
                        "anthropic_version": "bedrock-2023-05-31",
                        "max_tokens": 2048,
                        "temperature": 0.0,
                        "system": system_message,
                        "messages": [
                            {
                                "role": "user",
                                "content": message_content
                            }
                        ]
                    }),
                    accept="application/json",
                    contentType="application/json"
                )
                response_body = response["body"].read().decode()
                result_json = json.loads(response_body)
                # Extract content from the first message in the response (Messages API format)
                claude_content = result_json.get("content", [])[0].get("text", "") if result_json.get("content") else ""
                try:
                    structured_invoice = json.loads(claude_content)
                    
                    # Post-processing to ensure critical fields are complete
                    if isinstance(structured_invoice, dict):
                        # Check seller information
                        if "seller" in structured_invoice and isinstance(structured_invoice["seller"], dict):
                            # If seller has address but no name, try to extract name from the first line of address
                            if not structured_invoice["seller"].get("name") and structured_invoice["seller"].get("address"):
                                # Try to extract company name from address or use a placeholder
                                address_lines = structured_invoice["seller"]["address"].split(",")[0].strip()
                                if "Regd.Off." in address_lines:
                                    # Remove registration office prefix if present
                                    address_lines = address_lines.replace("Regd.Off.", "").strip()
                                structured_invoice["seller"]["name"] = address_lines
                        
                        # Ensure tax_details exists
                        if "tax_details" not in structured_invoice:
                            structured_invoice["tax_details"] = []
                            
                        # If line_items have tax_percentage but no tax_amount, calculate it
                        if "line_items" in structured_invoice and isinstance(structured_invoice["line_items"], list):
                            for item in structured_invoice["line_items"]:
                                if isinstance(item, dict) and "tax_percentage" in item and "amount" in item and "tax_amount" not in item:
                                    # Calculate tax amount based on percentage
                                    item["tax_amount"] = round(item["amount"] * (item["tax_percentage"] / 100), 2)
                                    
                    save_to_cache(input_file, processing_method, structured_invoice)
                    return structured_invoice
                except Exception as e:
                    print(f"Error parsing Claude response: {e}")
                    # If not valid JSON, return as string
                    save_to_cache(input_file, processing_method, {"error": str(e), "text": claude_content})
                    return {"error": str(e), "text": claude_content}
            except (BotoCoreError, ClientError, Exception) as e:
                print(f"Bedrock Claude Sonnet error: {e}")
                return {"error": str(e)}
        elif processing_method == "bedrock_data_automation":
            # Amazon Bedrock Data Automation integration
            print("Processing with Amazon Bedrock Data Automation...")
            # Required env vars: AWS_REGION, BDA_BUCKET_NAME, BDA_INPUT_PREFIX, BDA_OUTPUT_PREFIX, BDA_PROJECT_ID, BDA_BLUEPRINT_NAME
            # Use environment variables or fallback to user-provided constants
            AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
            BDA_BUCKET_NAME = os.getenv("BDA_BUCKET_NAME", "doc-ocr-poc")
            BDA_INPUT_PREFIX = os.getenv("BDA_INPUT_PREFIX", "bedrock-data-auto-temp/input")
            BDA_OUTPUT_PREFIX = os.getenv("BDA_OUTPUT_PREFIX", "bedrock-data-auto-temp/output")
            BDA_PROJECT_ID = os.getenv("BDA_PROJECT_ID", "4790fd771828")
            BDA_BLUEPRINT_NAME = os.getenv("BDA_BLUEPRINT_NAME", "default-blueprint")
            DATA_AUTOMATION_PROFILE_ARN = os.getenv("DATA_AUTOMATION_PROFILE_ARN", "arn:aws:bedrock:us-east-1:302263040839:data-automation-project/4790fd771828")
            CLAUDE_MODEL_ID = os.getenv("BEDROCK_CLAUDE_MODEL_ID", "arn:aws:bedrock:us-east-1:302263040839:inference-profile/us.anthropic.claude-3-5-sonnet-20240620-v1:0")
            bda = boto3.client('bedrock-data-automation-runtime', region_name=AWS_REGION)
            s3 = boto3.client('s3', region_name=AWS_REGION)
            sts = boto3.client('sts')
            
            def get_aws_account_id():
                return sts.get_caller_identity().get('Account')
            def upload_to_s3(local_path, bucket, key):
                s3.upload_file(local_path, bucket, key)
            def get_json_object_from_s3_uri(s3_uri):
                s3_uri_split = s3_uri.split('/')
                bucket = s3_uri_split[2]
                key = '/'.join(s3_uri_split[3:])
                object_content = s3.get_object(Bucket=bucket, Key=key)['Body'].read()
                return json.loads(object_content)
            aws_account_id = get_aws_account_id()
            file_name = os.path.basename(input_file)
            input_key = f"{BDA_INPUT_PREFIX}/{file_name}"
            output_prefix = BDA_OUTPUT_PREFIX
            upload_to_s3(input_file, BDA_BUCKET_NAME, input_key)
            input_s3_uri = f"s3://{BDA_BUCKET_NAME}/{input_key}"
            output_s3_uri = f"s3://{BDA_BUCKET_NAME}/{output_prefix}"
            data_automation_arn = f"arn:aws:bedrock:{AWS_REGION}:{aws_account_id}:data-automation-project/{BDA_PROJECT_ID}"
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
            # Poll for completion
            import time
            while True:
                status_response = bda.get_data_automation_status(invocationArn=invocation_arn)
                status = status_response['status']
                if status not in ['Created', 'InProgress']:
                    break
                time.sleep(2)
            if status_response['status'] == 'Success':
                job_metadata_s3_uri = status_response['outputConfiguration']['s3Uri']
                job_metadata = get_json_object_from_s3_uri(job_metadata_s3_uri)
                # Extract standard output (first segment/page)
                try:
                    segment = job_metadata['output_metadata'][0]
                    segment_metadata = segment['segment_metadata'][0]
                    standard_output_path = segment_metadata['standard_output_path']
                    standard_output_result = get_json_object_from_s3_uri(standard_output_path)
                    # Send the BDA output to Claude Sonnet for structured extraction
                    try:
                        # Extract markdown content if present (else fallback to full output)
                        bda_text = None
                        if isinstance(standard_output_result, dict):
                            # Try to extract all markdown representations
                            if 'output' in standard_output_result and isinstance(standard_output_result['output'], list):
                                markdowns = []
                                for item in standard_output_result['output']:
                                    rep = item.get('representation', {})
                                    if isinstance(rep, dict) and 'markdown' in rep:
                                        markdowns.append(rep['markdown'])
                                if markdowns:
                                    bda_text = '\n'.join(markdowns)
                            # Fallback: string representation
                            if not bda_text:
                                bda_text = json.dumps(standard_output_result)
                        else:
                            bda_text = str(standard_output_result)

                        # System message and user message for Claude 3.5 Sonnet
                        system_message = """You are an expert invoice parser. Extract all relevant invoice fields in structured JSON format from the document content and the invoice image. Respond ONLY with a JSON object matching the invoice schema, no extra text. 

Follow this exact schema structure for your JSON response:

{
  "invoice_number": "string",
  "invoice_date": "string (YYYY-MM-DD)",
  "due_date": "string (YYYY-MM-DD)",
  "payment_terms": "string",
  "currency": "string",
  "seller": {
    "name": "string",
    "address": "string",
    "gstin": "string",
    "pan": "string",
    "contact_details": "string"
  },
  "buyer": {
    "name": "string",
    "address": "string",
    "gstin": "string",
    "pan": "string",
    "contact_details": "string"
  },
  "line_items": [
    {
      "description": "string",
      "hsn_sac": "string",
      "quantity": number,
      "unit": "string",
      "unit_price": number,
      "tax_percentage": number,
      "tax_amount": number,
      "amount": number
    }
  ],
  "subtotal": number,
  "tax_details": [
    {
      "tax_type": "string (e.g., CGST, SGST, IGST)",
      "rate": number,
      "amount": number
    }
  ],
  "total_tax_amount": number,
  "total_amount": number,
  "amount_in_words": "string",
  "po_number": "string",
  "shipping_details": {
    "shipped_to": "string",
    "ship_to_address": "string",
    "place_of_supply": "string",
    "transporter": "string",
    "vehicle_number": "string",
    "dispatch_date": "string"
  },
  "bank_details": {
    "bank_name": "string",
    "account_number": "string",
    "ifsc_code": "string",
    "branch": "string"
  },
  "irn": "string",
  "ack_number": "string",
  "place_of_supply": "string",
  "reverse_charge": boolean,
  "notes": "string"
}

Important notes:
1. All fields are optional. If a field is not found in the document, omit it from the JSON rather than including it with a null or empty value.
2. Always include the tax_details array even if empty.
3. CRITICAL: You MUST use the key 'line_items' (not 'items') for the array of invoice line items as shown in the schema. The UI expects this exact field name."""
                        
                        # Convert PDF to image if needed
                        with tempfile.TemporaryDirectory() as temp_dir:
                            if input_file.lower().endswith(".pdf"):
                                image_path = convert_pdf_to_image(input_file, temp_dir)
                            else:
                                image_path = input_file
                                
                            # Read image as base64
                            with open(image_path, "rb") as img_file:
                                base64_image = base64.b64encode(img_file.read()).decode("utf-8")
                        
                            # Prepare multimodal message with both text and image
                            message_content = [
                                {
                                    "type": "text",
                                    "text": "Here is the extracted text from the invoice:" + "\n\n" + bda_text
                                },
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": "image/jpeg",
                                        "data": base64_image
                                    }
                                }
                            ]
                            
                            bedrock_client = boto3.client("bedrock-runtime", region_name=AWS_REGION)
                            
                            # Use the Messages API format for Claude 3.5 Sonnet with multimodal content
                            response = bedrock_client.invoke_model(
                                modelId=CLAUDE_MODEL_ID,
                                body=json.dumps({
                                    "anthropic_version": "bedrock-2023-05-31",
                                    "max_tokens": 2048,
                                    "temperature": 0.0,
                                    "system": system_message,
                                    "messages": [
                                        {
                                            "role": "user",
                                            "content": message_content
                                        }
                                    ]
                                }),
                                accept="application/json",
                                contentType="application/json"
                            )
                        
                        response_body = response["body"].read().decode()
                        result_json = json.loads(response_body)
                        # Extract content from the first message in the response
                        claude_content = result_json.get("content", [])[0].get("text", "") if result_json.get("content") else ""
                        try:
                            structured_invoice = json.loads(claude_content)
                            
                            # Post-processing to ensure critical fields are complete
                            if isinstance(structured_invoice, dict):
                                # Check seller information
                                if "seller" in structured_invoice and isinstance(structured_invoice["seller"], dict):
                                    # If seller has address but no name, try to extract name from the first line of address
                                    if not structured_invoice["seller"].get("name") and structured_invoice["seller"].get("address"):
                                        # Try to extract company name from address or use a placeholder
                                        address_lines = structured_invoice["seller"]["address"].split(",")[0].strip()
                                        if "Regd.Off." in address_lines:
                                            # Remove registration office prefix if present
                                            address_lines = address_lines.replace("Regd.Off.", "").strip()
                                        structured_invoice["seller"]["name"] = address_lines
                                
                                # Ensure tax_details exists
                                if "tax_details" not in structured_invoice:
                                    structured_invoice["tax_details"] = []
                                    
                                # If line_items have tax_percentage but no tax_amount, calculate it
                                if "line_items" in structured_invoice and isinstance(structured_invoice["line_items"], list):
                                    for item in structured_invoice["line_items"]:
                                        if isinstance(item, dict) and "tax_percentage" in item and "amount" in item and "tax_amount" not in item:
                                            # Calculate tax amount based on percentage
                                            item["tax_amount"] = round(item["amount"] * (item["tax_percentage"] / 100), 2)
                        except Exception:
                            structured_invoice = claude_content

                        save_to_cache(input_file, processing_method, structured_invoice)
                        return structured_invoice
                    except Exception as e:
                        print(f"Error sending BDA output to Claude Sonnet: {e}")
                        save_to_cache(input_file, processing_method, standard_output_result)
                        return standard_output_result
                except Exception as e:
                    print(f"BDA result extraction error: {e}")
                    return {"error": str(e)}
            else:
                print(f"BDA failed: {status_response}")
                return {"error": status_response}
        elif processing_method == "textract_claude":
            # Amazon Textract + Claude integration
            print("Processing with Amazon Textract + Claude...")
            
            # Required env vars: AWS_REGION
            AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
            CLAUDE_MODEL_ID = os.getenv("BEDROCK_CLAUDE_MODEL_ID", "arn:aws:bedrock:us-east-1:302263040839:inference-profile/us.anthropic.claude-3-5-sonnet-20240620-v1:0")
            
            # Convert PDF to image if needed, to ensure both image and text processing
            with tempfile.TemporaryDirectory() as temp_dir:
                if input_file.lower().endswith(".pdf"):
                    image_path = convert_pdf_to_image(input_file, temp_dir)
                else:
                    image_path = input_file
                    
                # Initialize Textract client
                textract = boto3.client('textract', region_name=AWS_REGION)
                
                # Extract text using Textract
                print("Extracting text with Amazon Textract...")
                
                # We've already converted any PDF to image above, so we can just use the image_path directly
                # Textract synchronous API only supports image formats (JPG, PNG, etc.)
                try:
                    # Read the image file
                    with open(image_path, 'rb') as document:
                        file_bytes = document.read()
                        
                    # Process with Textract
                    response = textract.detect_document_text(
                        Document={
                            'Bytes': file_bytes
                        }
                    )
                except Exception as e:
                    print(f"Textract error: {str(e)}")
                    # Fallback text if Textract fails
                    response = {'Blocks': []}
                    extracted_text = "Textract processing failed. Using only image analysis."
                
                # Parse Textract response
                extracted_text = ""
                if 'Blocks' in response:
                    for block in response['Blocks']:
                        if block['BlockType'] == 'LINE':
                            extracted_text += block['Text'] + "\n"
                
                # Read image as base64 for Claude
                with open(image_path, "rb") as img_file:
                    base64_image = base64.b64encode(img_file.read()).decode("utf-8")
                
                # System message for Claude
                system_message = """You are an expert invoice parser. Extract all relevant invoice fields in structured JSON format from the document content and the invoice image. Respond ONLY with a JSON object matching the invoice schema, no extra text. 

Follow this exact schema structure for your JSON response:

{
  "invoice_number": "string",
  "invoice_date": "string (YYYY-MM-DD)",
  "due_date": "string (YYYY-MM-DD)",
  "payment_terms": "string",
  "currency": "string",
  "seller": {
    "name": "string",
    "address": "string",
    "gstin": "string",
    "pan": "string",
    "contact_details": "string"
  },
  "buyer": {
    "name": "string",
    "address": "string",
    "gstin": "string",
    "pan": "string",
    "contact_details": "string"
  },
  "line_items": [
    {
      "description": "string",
      "hsn_sac": "string",
      "quantity": number,
      "unit": "string",
      "unit_price": number,
      "tax_percentage": number,
      "tax_amount": number,
      "amount": number
    }
  ],
  "subtotal": number,
  "tax_details": [
    {
      "tax_type": "string (e.g., CGST, SGST, IGST)",
      "rate": number,
      "amount": number
    }
  ],
  "total_tax_amount": number,
  "total_amount": number,
  "amount_in_words": "string",
  "po_number": "string",
  "shipping_details": {
    "shipped_to": "string",
    "ship_to_address": "string",
    "place_of_supply": "string",
    "transporter": "string",
    "vehicle_number": "string",
    "dispatch_date": "string"
  },
  "bank_details": {
    "bank_name": "string",
    "account_number": "string",
    "ifsc_code": "string",
    "branch": "string"
  },
  "irn": "string",
  "ack_number": "string",
  "place_of_supply": "string",
  "reverse_charge": boolean,
  "notes": "string"
}

Important notes:
1. All fields are optional. If a field is not found in the document, omit it from the JSON rather than including it with a null or empty value.
2. Always include the tax_details array even if empty.
3. CRITICAL: You MUST use the key 'line_items' (not 'items') for the array of invoice line items as shown in the schema. The UI expects this exact field name."""
                
                # Prepare multimodal message with both Textract text and image
                message_content = [
                    {
                        "type": "text",
                        "text": "Here is the extracted text from the invoice using Amazon Textract:" + "\n\n" + extracted_text
                    },
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": base64_image
                        }
                    }
                ]
                
                try:
                    # Call Claude with Textract data and image
                    print("Sending Textract output and image to Claude...")
                    bedrock_client = boto3.client("bedrock-runtime", region_name=AWS_REGION)
                    
                    # Use the Messages API format for Claude 3.5 Sonnet with multimodal content
                    response = bedrock_client.invoke_model(
                        modelId=CLAUDE_MODEL_ID,
                        body=json.dumps({
                            "anthropic_version": "bedrock-2023-05-31",
                            "max_tokens": 2048,
                            "temperature": 0.0,
                            "system": system_message,
                            "messages": [
                                {
                                    "role": "user",
                                    "content": message_content
                                }
                            ]
                        }),
                        accept="application/json",
                        contentType="application/json"
                    )
                    
                    response_body = response["body"].read().decode()
                    result_json = json.loads(response_body)
                    # Extract content from the first message in the response
                    claude_content = result_json.get("content", [])[0].get("text", "") if result_json.get("content") else ""
                    
                    try:
                        structured_invoice = json.loads(claude_content)
                        
                        # Post-processing to ensure critical fields are complete
                        if isinstance(structured_invoice, dict):
                            # Check seller information
                            if "seller" in structured_invoice and isinstance(structured_invoice["seller"], dict):
                                # If seller has address but no name, try to extract name from the first line of address
                                if not structured_invoice["seller"].get("name") and structured_invoice["seller"].get("address"):
                                    # Try to extract company name from address or use a placeholder
                                    address_lines = structured_invoice["seller"]["address"].split(",")[0].strip()
                                    if "Regd.Off." in address_lines:
                                        # Remove registration office prefix if present
                                        address_lines = address_lines.replace("Regd.Off.", "").strip()
                                    structured_invoice["seller"]["name"] = address_lines
                            
                            # Ensure tax_details exists
                            if "tax_details" not in structured_invoice:
                                structured_invoice["tax_details"] = []
                                
                            # If line_items have tax_percentage but no tax_amount, calculate it
                            if "line_items" in structured_invoice and isinstance(structured_invoice["line_items"], list):
                                for item in structured_invoice["line_items"]:
                                    if isinstance(item, dict) and "tax_percentage" in item and "amount" in item and "tax_amount" not in item:
                                        # Calculate tax amount based on percentage
                                        item["tax_amount"] = round(item["amount"] * (item["tax_percentage"] / 100), 2)
                                        
                        save_to_cache(input_file, processing_method, structured_invoice)
                        return structured_invoice
                    except Exception as e:
                        print(f"Error parsing Claude response: {e}")
                        save_to_cache(input_file, processing_method, {"error": str(e), "text": extracted_text})
                        return {"error": str(e), "text": extracted_text}
                except Exception as e:
                    print(f"Error processing with Textract+Claude: {e}")
                    return {"error": str(e)}
        elif processing_method == "di_gpt_no_image":
            # Call GPT-4o with Document Intelligence results WITHOUT image
            print("Sending Document Intelligence results WITHOUT image to GPT-4o")
            # Modified prompt for DI+GPT without image method
            di_system_prompt = system_prompt + "\n\nThe document has already been processed by Document Intelligence, and the extracted text is provided to you."
            
            response = openai_client.beta.chat.completions.parse(
                model=deployment_name,
                messages=[
                    {"role": "system", "content": di_system_prompt},
                    {"role": "user", "content": f"Here is the extracted text from the invoice:\n\n{doc_result.content}\n\nPlease extract the information according to the model structure."}
                ],
                response_format=Invoice,
            )
        
        # Parse the response based on which method was used
        if processing_method == 'di_phi':
            # The complete method returns a different structure than the OpenAI client
            phi_response_text = response.choices[0].message.content
            try:
                # The Phi model may return invalid JSON with commas in numeric values
                # Clean up the response first
                import re
                # This regex finds numeric values with commas (e.g., 169,050.28) not inside quotes
                cleaned_text = re.sub(r'(?<!\"): (\d+),(\d+\.\d+)', r': \1\2', phi_response_text)
                # Also clean up any other instances of invalid JSON with commas in numbers
                cleaned_text = re.sub(r'(?<!\"): (\d+),(\d+),(\d+\.\d+)', r': \1\2\3', cleaned_text)
                
                print(f"Cleaned response for parsing")
                
                # Parse the cleaned response into a Python dict first
                parsed_dict = json.loads(cleaned_text)
                
                # Fix boolean fields that might contain strings like 'Not provided'
                if 'reverse_charge' in parsed_dict and parsed_dict['reverse_charge'] in ['Not provided', 'not provided', None, '']:
                    parsed_dict['reverse_charge'] = None
                
                # Fix field name mismatches in seller/buyer info
                if 'seller_info' in parsed_dict and 'seller' not in parsed_dict:
                    parsed_dict['seller'] = parsed_dict.pop('seller_info')
                
                if 'buyer_info' in parsed_dict and 'buyer' not in parsed_dict:
                    parsed_dict['buyer'] = parsed_dict.pop('buyer_info')
                
                # Now validate with the model
                parsed_result = Invoice.model_validate(parsed_dict)
                print(f"Successfully parsed PHI response: {type(parsed_result)}")
            except Exception as e:
                print(f"Error parsing PHI response: {e}")
                print(f"PHI response: {phi_response_text}")
                # Try a more aggressive cleaning - replace all commas between digits
                try:
                    # This regex removes all commas that appear between digits
                    aggressive_clean = re.sub(r'(\d),(\d)', r'\1\2', phi_response_text)
                    aggressive_dict = json.loads(aggressive_clean)
                    
                    # Fix boolean fields that might contain strings like 'Not provided'
                    if 'reverse_charge' in aggressive_dict and aggressive_dict['reverse_charge'] in ['Not provided', 'not provided', None, '']:
                        aggressive_dict['reverse_charge'] = None
                    
                    # Fix field name mismatches in seller/buyer info
                    if 'seller_info' in aggressive_dict and 'seller' not in aggressive_dict:
                        aggressive_dict['seller'] = aggressive_dict.pop('seller_info')
                    
                    if 'buyer_info' in aggressive_dict and 'buyer' not in aggressive_dict:
                        aggressive_dict['buyer'] = aggressive_dict.pop('buyer_info')
                    
                    parsed_result = Invoice.model_validate(aggressive_dict)
                    print(f"Successfully parsed PHI response with aggressive cleaning")
                except Exception as e2:
                    print(f"Even aggressive cleaning failed: {e2}")
                    raise
        else:
            # For OpenAI methods, the parsed response is already available
            parsed_result = response.choices[0].message.parsed
        
        # Print debug information about the result
        print(f"Result type: {type(parsed_result)}")
        print(f"Result has model_dump(): {hasattr(parsed_result, 'model_dump')}")
        print(f"Result has dict(): {hasattr(parsed_result, 'dict')}")
        print(f"Result model_dump(): {parsed_result.model_dump()}")
        
        # Save result to cache for future use
        save_to_cache(input_file, processing_method, parsed_result)
        
        return parsed_result
    finally:
        # Clean up the temporary directory
        if os.path.exists(temp_dir):
            import shutil
            shutil.rmtree(temp_dir)

def process_invoice_directory(doc_intelligence_endpoint: str,
                           doc_intelligence_key: str,
                           openai_endpoint: str,
                           openai_key: str,
                           deployment_name: str,
                           input_dir: str,
                           output_dir: str):
    """Process all invoices in a directory and save their results"""
    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)
    
    # Get list of all PDF and image files
    valid_extensions = ('.pdf', '.jpg', '.jpeg', '.png', '.tiff')
    invoice_files = [f for f in os.listdir(input_dir) 
                    if f.lower().endswith(valid_extensions)]
    
    results = []
    for idx, filename in enumerate(invoice_files, 1):
        print(f"Processing invoice {idx}/{len(invoice_files)}: {filename}")
        try:
            # Process invoice
            input_path = os.path.join(input_dir, filename)
            result = analyze_and_parse_invoice(
                doc_intelligence_endpoint,
                doc_intelligence_key,
                openai_endpoint,
                openai_key,
                deployment_name,
                input_path
            )
            
            # Save individual result
            print(f"Result: {result.model_dump()}")
            output_filename = f"{os.path.splitext(filename)[0]}_parsed.json"
            output_path = os.path.join(output_dir, output_filename)
            with open(output_path, 'w') as f:
                json.dump(result.model_dump(), f, indent=2)
            
            results.append({
                'filename': filename,
                'status': 'success',
                'data': result.model_dump()
            })
            
        except Exception as e:
            print(f"Error processing {filename}: {str(e)}")
            results.append({
                'filename': filename,
                'status': 'error',
                'error': str(e)
            })
    
    # Save summary report
    summary = {
        'total_processed': len(invoice_files),
        'successful': len([r for r in results if r['status'] == 'success']),
        'failed': len([r for r in results if r['status'] == 'error']),
        'results': results
    }
    
    with open(os.path.join(output_dir, 'processing_summary.json'), 'w') as f:
        json.dump(summary, f, indent=2)
    
    return summary

# Environment variables were loaded at the top of the file

# Azure Document Intelligence and OpenAI configuration
DOC_INTELLIGENCE_ENDPOINT = os.getenv("DOC_INTELLIGENCE_ENDPOINT")
DOC_INTELLIGENCE_KEY = os.getenv("DOC_INTELLIGENCE_KEY")
OPENAI_ENDPOINT = os.getenv("OPENAI_ENDPOINT")
OPENAI_KEY = os.getenv("OPENAI_KEY")
DEPLOYMENT_NAME = os.getenv("DEPLOYMENT_NAME", "gpt-4o")

# Add new settings for DI+Phi
PHI_DI_ENDPOINT = os.getenv("PHI_DI_ENDPOINT")
PHI_DI_KEY = os.getenv("PHI_DI_KEY")

# Add processing method options
PROCESSING_METHODS = [
    "bedrock_claude_sonnet",  # Amazon Bedrock Claude Sonnet
    "bedrock_data_automation",  # Amazon Bedrock Data Automation
    "textract_claude"  # Amazon Textract + Claude
]

# Flask application configuration
app = Flask(__name__, static_folder='static')
app.config['SECRET_KEY'] = os.urandom(24)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload

# Add custom filter to extract filename from path
@app.template_filter('basename')
def basename_filter(path):
    return os.path.basename(path) if path else ''

# Add custom filter to format timestamps
@app.template_filter('datetime')
def datetime_filter(timestamp):
    dt = datetime.fromtimestamp(timestamp)
    return dt.strftime('%Y-%m-%d %H:%M')

# Add URL encoding filter
@app.template_filter('urlencode')
def urlencode_filter(s):
    if isinstance(s, str):
        import urllib.parse
        return urllib.parse.quote(s)
    return s

# Add JSON formatting filter
@app.template_filter('tojson')
def tojson_filter(obj, indent=None):
    if obj is None:
        return json.dumps(None, indent=indent)
    try:
        serialized = serialize_model(obj) if hasattr(obj, 'dict') or hasattr(obj, 'model_dump') else obj
        return json.dumps(serialized, indent=indent, default=str)
    except Exception as e:
        return json.dumps({'error': str(e)}, indent=indent)

# Helper class to emulate a Pydantic model but as a dotted dict
class DotDict:
    def __init__(self, data):
        self.__dict__.update(data)
        
    def __getattr__(self, name):
        return self.__dict__.get(name)
    
    def keys(self):
        return self.__dict__.keys()
    
    def get(self, key, default=None):
        return self.__dict__.get(key, default)
    
    # Add special methods to make Jinja2 template interactions better
    def __iter__(self):
        return iter(self.__dict__)
    
    def __contains__(self, key):
        return key in self.__dict__
        
    def __bool__(self):
        return bool(self.__dict__)
        
# Helper function to convert Pydantic models to DotDict or dict for JSON serialization
def serialize_model(obj):
    # Handle None case explicitly
    if obj is None:
        return None
    
    # Lists - process each item
    if isinstance(obj, list):
        return [serialize_model(item) for item in obj]
    
    # Dictionaries - process each value
    if isinstance(obj, dict):
        return {k: serialize_model(v) for k, v in obj.items()}
    
    # Handle Pydantic models
    data = None
    if hasattr(obj, 'model_dump') and callable(obj.model_dump):
        try:
            data = obj.model_dump()
        except Exception:
            # If model_dump fails, try the next method
            pass
    
    if data is None and hasattr(obj, 'dict') and callable(obj.dict):
        try:
            data = obj.dict()
        except Exception:
            # If dict fails, use __dict__ as fallback
            pass
    
    # If it's not a Pydantic model or dict/list extraction failed
    if data is None:
        # Try to get __dict__ if available, otherwise return the object as is
        if hasattr(obj, '__dict__'):
            data = obj.__dict__
        else:
            return obj
    
    # Process dictionary data
    if isinstance(data, dict):
        # Handle special keys to avoid conflict with dict methods
        if 'items' in data:
            data['line_items'] = data['items']
        
        # Ensure tax_amount is available as a field for backwards compatibility
        if 'total_tax_amount' in data and 'tax_amount' not in data:
            data['tax_amount'] = data['total_tax_amount']
        
        # For JSON serialization, we can return a regular dict
        return {k: serialize_model(v) for k, v in data.items()}
    
    return data

# Convert dictionary to DotDict for attribute access
def to_dot_dict(data):
    if data is None:
        return None
    
    if isinstance(data, list):
        return [to_dot_dict(item) for item in data]
    
    if not isinstance(data, dict):
        return data
    
    dot_dict = DotDict(data)
    
    # Convert nested dictionaries
    for key, value in data.items():
        if isinstance(value, dict):
            dot_dict.__dict__[key] = to_dot_dict(value)
        elif isinstance(value, list):
            dot_dict.__dict__[key] = [to_dot_dict(item) if isinstance(item, (dict, list)) else item for item in value]
    
    return dot_dict

# Create necessary directories if they don't exist
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

# Create cache directory for storing processed results
CACHE_DIR = os.path.join(app.config['UPLOAD_FOLDER'], 'cache')
if not os.path.exists(CACHE_DIR):
    os.makedirs(CACHE_DIR)

# Cache functions for storing and retrieving processed results
def get_cache_key(file_path, processing_method):
    """Generate a unique cache key based on file path and processing method"""
    # Use hash of the file path and processing method to create a unique identifier
    import hashlib
    file_hash = hashlib.md5(file_path.encode()).hexdigest()
    return f"{file_hash}_{processing_method}"

def clear_cache(file_path=None):
    """Clear cache for a specific file or all files"""
    if file_path:
        # Clear cache for specific file only
        for method in PROCESSING_METHODS:
            cache_key = get_cache_key(file_path, method)
            cache_file = os.path.join(CACHE_DIR, f"{cache_key}.json")
            if os.path.exists(cache_file):
                os.remove(cache_file)
                print(f"Cleared cache for {os.path.basename(file_path)} with {method}")
    else:
        # Clear all cache files
        if os.path.exists(CACHE_DIR):
            for cache_file in os.listdir(CACHE_DIR):
                if cache_file.endswith('.json'):
                    os.remove(os.path.join(CACHE_DIR, cache_file))
            print("Cleared all cache files")

def get_cached_result(file_path, processing_method):
    """Get cached result if it exists"""
    cache_key = get_cache_key(file_path, processing_method)
    cache_file = os.path.join(CACHE_DIR, f"{cache_key}.json")
    
    if os.path.exists(cache_file):
        try:
            # Get file modification time to check if the original file has changed
            cache_mtime = os.path.getmtime(cache_file)
            file_mtime = os.path.getmtime(file_path)
            
            # If the original file is newer than the cache, don't use the cache
            if file_mtime > cache_mtime:
                return None
                
            with open(cache_file, 'r') as f:
                cached_data = json.load(f)
            print(f"Using cached result for {os.path.basename(file_path)} with {processing_method}")
            return Invoice.model_validate(cached_data)
        except Exception as e:
            print(f"Error loading cache: {e}")
            return None
    return None

def save_to_cache(file_path, processing_method, result):
    """Save processed result to cache"""
    cache_key = get_cache_key(file_path, processing_method)
    cache_file = os.path.join(CACHE_DIR, f"{cache_key}.json")
    
    try:
        with open(cache_file, 'w') as f:
            # Support both Pydantic models and dicts for caching
            if hasattr(result, 'model_dump'):
                json.dump(result.model_dump(exclude_none=True), f, indent=2)
            elif isinstance(result, dict):
                json.dump(result, f, indent=2)
            else:
                json.dump(str(result), f, indent=2)
        print(f"Saved result to cache for {os.path.basename(file_path)} with {processing_method}")
    except Exception as e:
        print(f"Error saving to cache: {e}")
        
def create_thumbnail(file_path):
    """Create a thumbnail for PDF files"""
    try:
        # Create thumbnails directory if it doesn't exist
        thumbnails_dir = os.path.join(app.config['UPLOAD_FOLDER'], 'thumbnails')
        if not os.path.exists(thumbnails_dir):
            os.makedirs(thumbnails_dir)
            
        # Generate thumbnail name
        filename = os.path.basename(file_path)
        thumbnail_path = os.path.join(thumbnails_dir, f"{os.path.splitext(filename)[0]}_thumbnail.jpg")
        
        # Only create thumbnail if it doesn't exist
        if not os.path.exists(thumbnail_path):
            # Convert first page of PDF to image
            images = convert_from_path(file_path, first_page=1, last_page=1, dpi=72)
            if images:
                # Save the first page as thumbnail
                images[0].save(thumbnail_path, 'JPEG')
                print(f"Created thumbnail for {filename}")
                
        return thumbnail_path
    except Exception as e:
        print(f"Error creating thumbnail: {e}")
        return None



@app.route('/')
def index():
    # Get list of previously uploaded files
    uploaded_files = []
    if os.path.exists(app.config['UPLOAD_FOLDER']):
        for filename in os.listdir(app.config['UPLOAD_FOLDER']):
            if filename.lower().endswith('.pdf'):
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file_size = os.path.getsize(file_path)
                file_date = os.path.getmtime(file_path)
                uploaded_files.append({
                    'name': filename,
                    'path': file_path,
                    'size': file_size,
                    'date': file_date
                })
    
    # Sort files by date (newest first)
    uploaded_files.sort(key=lambda x: x['date'], reverse=True)
    
    # Return an empty result for the initial page
    return render_template('index.html', 
                           result=None, 
                           uploaded_file_path=None, 
                           uploaded_files=uploaded_files,
                           debug_mode=False,
                           model_definitions=None)

@app.route('/upload', methods=['POST'])
def upload_file():
    """Step 1: Just upload the file and return the path"""
    # Get list of previously uploaded files
    uploaded_files = []
    if os.path.exists(app.config['UPLOAD_FOLDER']):
        for filename in os.listdir(app.config['UPLOAD_FOLDER']):
            if filename.lower().endswith('.pdf'):
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file_size = os.path.getsize(file_path)
                file_date = os.path.getmtime(file_path)
                uploaded_files.append({
                    'name': filename,
                    'path': file_path,
                    'size': file_size,
                    'date': file_date
                })
    
    # Sort files by date (newest first)
    uploaded_files.sort(key=lambda x: x['date'], reverse=True)
    
    if 'file' not in request.files:
        flash('No file part')
        return render_template('index.html', uploaded_file_path=None, uploaded_files=uploaded_files)
    
    file = request.files['file']
    if file.filename == '':
        flash('No selected file')
        return render_template('index.html', uploaded_file_path=None, uploaded_files=uploaded_files)
    
    if file and file.filename.lower().endswith('.pdf'):
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        # Update the uploaded files list with the new file
        uploaded_files = [{
            'name': filename,
            'path': filepath,
            'size': os.path.getsize(filepath),
            'date': os.path.getmtime(filepath)
        }] + uploaded_files
        
        # Return the template with the uploaded file path
        return render_template('index.html', uploaded_file_path=filepath, result=None, uploaded_files=uploaded_files)
    else:
        flash('Invalid file type. Please upload a PDF file.')
        return render_template('index.html', uploaded_file_path=None, uploaded_files=uploaded_files)

@app.route('/analyze', methods=['POST'])
def analyze_file():
    """Step 2: Process the already uploaded file"""
    import time
    start_time = time.time()
    file_path = request.form.get('file_path')
    
    # Get list of previously uploaded files
    uploaded_files = []
    if os.path.exists(app.config['UPLOAD_FOLDER']):
        for filename in os.listdir(app.config['UPLOAD_FOLDER']):
            if filename.lower().endswith('.pdf'):
                file_path_item = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file_size = os.path.getsize(file_path_item)
                file_date = os.path.getmtime(file_path_item)
                uploaded_files.append({
                    'name': filename,
                    'path': file_path_item,
                    'size': file_size,
                    'date': file_date
                })
    
    # Sort files by date (newest first)
    uploaded_files.sort(key=lambda x: x['date'], reverse=True)
    
    if not file_path or not os.path.exists(file_path):
        flash('File not found. Please upload a file first.')
        return render_template('index.html', uploaded_file_path=None, uploaded_files=uploaded_files)
    
    # Get the processing method from the form
    processing_method = request.form.get('processing_method')
    
    # Validate that a processing method is selected
    if not processing_method:
        flash('Please select a processing method before running analysis.')
        return render_template('index.html', uploaded_file_path=file_path, uploaded_files=uploaded_files)
    try:
        result = analyze_and_parse_invoice(
            doc_intelligence_endpoint=DOC_INTELLIGENCE_ENDPOINT,
            doc_intelligence_key=DOC_INTELLIGENCE_KEY,
            openai_endpoint=OPENAI_ENDPOINT,
            openai_key=OPENAI_KEY,
            deployment_name=DEPLOYMENT_NAME,
            input_file=file_path,
            processing_method=processing_method
        )
        # Create a serialized version for JSON display
        json_result = serialize_model(result)
        
        # Create a DotDict version for template attribute access
        result_dict = to_dot_dict(json_result)
        
        # Add tax details if not present but we can detect them from other fields
        import re
        if not result_dict.tax_details or len(result_dict.tax_details) == 0:
            # If IGST is mentioned in the amount in words or we have a tax amount but no tax details
            has_igst_reference = False
            if result_dict.amount_in_words and 'IGST' in result_dict.amount_in_words:
                has_igst_reference = True
            elif result_dict.tax_amount and not result_dict.tax_details:
                has_igst_reference = True
                
            # Check for IGST elsewhere in the invoice data
            if not has_igst_reference:
                # Search in other text fields
                for key in ['notes', 'payment_terms']:
                    if hasattr(result_dict, key) and result_dict.get(key) and 'IGST' in str(result_dict.get(key)):
                        has_igst_reference = True
                        break
                        
            if has_igst_reference:
                tax_rate = None
                tax_amount = None
                
                # Try to extract tax rate from the template output
                # Try to find percentages in various fields
                percentage_sources = []
                if hasattr(result_dict, 'amount_in_words') and result_dict.amount_in_words:
                    percentage_sources.append(result_dict.amount_in_words)
                if hasattr(result_dict, 'notes') and result_dict.notes:
                    percentage_sources.append(result_dict.notes)
                if hasattr(result_dict, 'payment_terms') and result_dict.payment_terms:
                    percentage_sources.append(result_dict.payment_terms)
                    
                for source in percentage_sources:
                    # Try both IGST specific percentage and any percentage
                    igst_match = re.search(r'IGST\s*\(?(\d+(\.\d+)?)\%?\)?', source)
                    if igst_match:
                        tax_rate = float(igst_match.group(1))
                        break
                    
                    # If no IGST specific percentage, look for any percentage
                    percentage_match = re.search(r'(\d+(\.\d+)?)\s*\%', source)
                    if percentage_match:
                        tax_rate = float(percentage_match.group(1))
                        break
                
                # If we have a tax amount but no tax details
                if hasattr(result_dict, 'tax_amount') and result_dict.tax_amount:
                    tax_amount = result_dict.tax_amount
                elif hasattr(result_dict, 'total_tax_amount') and result_dict.total_tax_amount:
                    tax_amount = result_dict.total_tax_amount
                
                # Create a tax detail object if we have either rate or amount
                if tax_rate or tax_amount:
                    result_dict.tax_details = [DotDict({
                        'tax_type': 'IGST',
                        'rate': tax_rate,
                        'amount': tax_amount
                    })]
        
        # Do not include any model definitions in the template context
        # Only pass the actual data needed for rendering
        # Ensure tax_details is always a list even if it's None
        if result_dict is not None:
            # Convert to regular dict if it's a DotDict
            if isinstance(result_dict, DotDict):
                # If it's a DotDict, check and set tax_details in __dict__
                if result_dict.get('tax_details') is None:
                    result_dict.__dict__['tax_details'] = []
            elif isinstance(result_dict, dict) and result_dict.get('tax_details') is None:
                # Regular dictionary case
                result_dict['tax_details'] = []
        
        print(f"Parsed result: {result_dict}")
        # Calculate processing time in seconds
        processing_time = time.time() - start_time
        return render_template('index.html', 
                            result=result_dict,
                            json_result=json_result, 
                            uploaded_file_path=file_path, 
                            debug_mode=False, 
                            uploaded_files=uploaded_files, 
                            model_definitions=None,
                            processing_complete=True,
                            processing_time=processing_time,
                            processing_method=processing_method)
    except Exception as e:
        import traceback
        print(f"Error processing file: {str(e)}")
        print(traceback.format_exc())
        flash(f'Error processing file: {str(e)}')
        # Even on error, calculate processing time
        processing_time = time.time() - start_time
        return render_template('index.html', 
                            result=None,
                            uploaded_file_path=file_path, 
                            uploaded_files=uploaded_files,
                            debug_mode=False,
                            model_definitions=None,
                            processing_time=processing_time,
                            processing_method=processing_method)

@app.route('/view')
def view_document():
    """View a document without analyzing it"""
    file_path = request.args.get('file_path')
    if not file_path or not os.path.exists(file_path):
        flash('File not found')
        return redirect('/')
    
    # Get list of all uploaded files
    uploaded_files = []
    if os.path.exists(app.config['UPLOAD_FOLDER']):
        for filename in os.listdir(app.config['UPLOAD_FOLDER']):
            if filename.lower().endswith('.pdf'):
                file_path_item = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file_size = os.path.getsize(file_path_item)
                file_date = os.path.getmtime(file_path_item)
                uploaded_files.append({
                    'name': filename,
                    'path': file_path_item,
                    'size': file_size,
                    'date': file_date
                })
    
    # Sort files by date (newest first)
    uploaded_files.sort(key=lambda x: x['date'], reverse=True)
    
    return render_template('index.html',
                           result=None,
                           uploaded_file_path=file_path, 
                           uploaded_files=uploaded_files,
                           debug_mode=False,
                           model_definitions=None)

@app.route('/preview')
def preview_document():
    """Return the contents of a file for preview"""
    file_path = request.args.get('file_path')
    if not file_path or not os.path.exists(file_path):
        return 'File not found', 404
    
    # For PDF files, serve the file directly
    if file_path.lower().endswith('.pdf'):
        return send_file(file_path, mimetype='application/pdf')
    
    return 'Preview not available for this file type', 400

@app.route('/download')
def download_document():
    """Download a file"""
    file_path = request.args.get('file_path')
    if not file_path or not os.path.exists(file_path):
        return 'File not found', 404
    
    filename = os.path.basename(file_path)
    return send_file(file_path, as_attachment=True, download_name=filename)

@app.route('/view_invoice/<path:filename>')
def view_invoice(filename):
    """View an invoice PDF file"""
    # Remove 'uploads/' from the beginning if it's there
    if filename.startswith('uploads/'):
        filename = filename[8:] # Remove 'uploads/' prefix
    
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    if not os.path.exists(file_path):
        return 'File not found', 404
    
    return send_file(file_path, mimetype='application/pdf')

@app.route('/compare/<path:file_path>', methods=['GET'])
def compare_methods(file_path):
    """Compare results across all processing methods for a single file"""
    
    if not os.path.isfile(file_path):
        flash('File not found!')
        return redirect(url_for('index'))
    
    results = {}
    json_results = {}
    
    try:
        # Process with all methods
        for method in PROCESSING_METHODS:
            # analyze_and_parse_invoice already uses caching internally
            result = analyze_and_parse_invoice(
                doc_intelligence_endpoint=DOC_INTELLIGENCE_ENDPOINT,
                doc_intelligence_key=DOC_INTELLIGENCE_KEY,
                openai_endpoint=OPENAI_ENDPOINT,
                openai_key=OPENAI_KEY,
                deployment_name=DEPLOYMENT_NAME,
                input_file=file_path,
                processing_method=method
            )
            # Create serialized version for JSON display
            json_result = serialize_model(result)
            
            # Create DotDict version for template attribute access
            results[method] = to_dot_dict(json_result)
            
            # Store the JSON result separately
            json_results[method] = json_result
        
        # Get just the filename for display
        filename = os.path.basename(file_path)
        
        return render_template(
            'compare.html', 
            results=results,
            json_results=json_results, 
            file_path=file_path, 
            filename=filename
        )
        
    except Exception as e:
        app.logger.error(f"Error in comparison: {str(e)}")
        app.logger.error(traceback.format_exc())
        flash(f'Error processing file: {str(e)}')
        return redirect(url_for('index'))

@app.route('/clear-cache', methods=['POST'])
def clear_cache_route():
    """Clear all cached results"""
    clear_cache()
    flash('Cache cleared successfully')
    return redirect(url_for('index'))

@app.route('/clear-cache/<path:file_path>', methods=['POST'])
def clear_cache_for_file(file_path):
    """Clear cached results for a specific file"""
    clear_cache(file_path)
    flash(f'Cache cleared for {os.path.basename(file_path)}')
    return redirect(url_for('index'))

# Search functionality
@app.route('/search', methods=['GET'])
def search():
    """Search for processed invoices"""
    query = request.args.get('query', '').strip().lower()
    filter_type = request.args.get('filter', None)
    
    # Get all the processed files from the cache directory
    cache_dir = os.path.join(app.config['UPLOAD_FOLDER'], 'cache')
    results = []
    
    if os.path.exists(cache_dir):
        for filename in os.listdir(cache_dir):
            if filename.endswith('.json'):
                try:
                    with open(os.path.join(cache_dir, filename), 'r') as f:
                        cache_data = json.load(f)
                        
                        # Get the original filename without the method suffix
                        original_filename = filename.rsplit('_', 1)[0].replace('.json', '')
                        
                        # Check if we have result data for any method
                        for method, result in cache_data.items():
                            if result and isinstance(result, dict):
                                # Extract basic info for display
                                invoice_data = {
                                    'filename': original_filename,
                                    'file_path': os.path.join(app.config['UPLOAD_FOLDER'], original_filename),
                                    'invoice_number': result.get('invoice_number', 'N/A'),
                                    'date': result.get('invoice_date', 'N/A'),
                                    'vendor': result.get('seller', {}).get('name', 'N/A') if isinstance(result.get('seller'), dict) else 'N/A',
                                    'amount': result.get('total_amount', 'N/A'),
                                    'method': method
                                }
                                
                                # Only include results that match the search query if provided
                                if not query or query in str(invoice_data).lower():
                                    # Apply filter if provided
                                    if filter_type:
                                        if filter_type == 'vendor' and query in str(invoice_data['vendor']).lower():
                                            results.append(invoice_data)
                                        elif filter_type == 'amount' and query in str(invoice_data['amount']).lower():
                                            results.append(invoice_data)
                                        elif filter_type == 'date' and query in str(invoice_data['date']).lower():
                                            results.append(invoice_data)
                                        elif filter_type == 'invoice_number' and query in str(invoice_data['invoice_number']).lower():
                                            results.append(invoice_data)
                                    else:
                                        results.append(invoice_data)
                                        
                                # Only include one result per file
                                break
                except Exception as e:
                    print(f"Error processing cache file {filename}: {e}")
    
    # Remove duplicates (same file processed with different methods)
    unique_results = []
    filenames_seen = set()
    for result in results:
        if result['filename'] not in filenames_seen:
            unique_results.append(result)
            filenames_seen.add(result['filename'])
    
    return render_template('search.html', results=unique_results)

# Settings related routes
@app.route('/settings', methods=['GET'])
def settings():
    """Display settings page for API configurations"""
    current_settings = {
        'doc_intelligence_endpoint': DOC_INTELLIGENCE_ENDPOINT,
        'doc_intelligence_key': mask_api_key(DOC_INTELLIGENCE_KEY),
        'openai_endpoint': OPENAI_ENDPOINT,
        'openai_key': mask_api_key(OPENAI_KEY),
        'deployment_name': DEPLOYMENT_NAME,
        'default_processing_method': 'bedrock_claude_sonnet',  # Default
        'cache_enabled': True  # Default
    }
    
    # Load saved settings from file if exists
    settings_file = os.path.join(os.path.dirname(__file__), 'settings.json')
    if os.path.exists(settings_file):
        try:
            with open(settings_file, 'r') as f:
                saved_settings = json.load(f)
                # Only update non-sensitive settings from the file
                if 'default_processing_method' in saved_settings:
                    current_settings['default_processing_method'] = saved_settings['default_processing_method']
                if 'cache_enabled' in saved_settings:
                    current_settings['cache_enabled'] = saved_settings['cache_enabled']
        except Exception as e:
            print(f"Error loading settings: {e}")
    
    return render_template('settings.html', settings=current_settings)

@app.route('/save_settings', methods=['POST'])
def save_settings():
    """Save settings to a local file"""
    # Only save non-sensitive settings to file
    settings_to_save = {
        'default_processing_method': request.form.get('default_processing_method', 'di_gpt_image'),
        'cache_enabled': 'cache_enabled' in request.form
    }
    
    # Handle API settings - these would typically update environment variables or secrets store
    # For this demo, we'll just show a message that they were updated
    api_settings_updated = False
    if request.form.get('doc_intelligence_endpoint') and request.form.get('doc_intelligence_endpoint') != DOC_INTELLIGENCE_ENDPOINT:
        api_settings_updated = True
    if request.form.get('doc_intelligence_key') and not all(c == '*' for c in request.form.get('doc_intelligence_key')):
        api_settings_updated = True
    if request.form.get('openai_endpoint') and request.form.get('openai_endpoint') != OPENAI_ENDPOINT:
        api_settings_updated = True
    if request.form.get('openai_key') and not all(c == '*' for c in request.form.get('openai_key')):
        api_settings_updated = True
    if request.form.get('deployment_name') and request.form.get('deployment_name') != DEPLOYMENT_NAME:
        api_settings_updated = True
        
    # Save settings to file
    settings_file = os.path.join(os.path.dirname(__file__), 'settings.json')
    try:
        with open(settings_file, 'w') as f:
            json.dump(settings_to_save, f, indent=2)
        flash('Settings saved successfully!', 'success')
        if api_settings_updated:
            flash('Note: API settings changes will take effect after restarting the application.', 'info')
    except Exception as e:
        flash(f'Error saving settings: {e}', 'error')
    
    return redirect(url_for('settings'))

# Helper function to mask API keys
def mask_api_key(key):
    """Mask an API key for display"""
    if not key:
        return ""
    return key[:4] + "*" * (len(key) - 8) + key[-4:] if len(key) > 8 else "*" * len(key)

if __name__ == "__main__":
    app.run(debug=True, port=5001)

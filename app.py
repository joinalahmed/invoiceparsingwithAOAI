import os
import json
import base64
import tempfile
from mimetypes import guess_type
from typing import List, Optional
from pydantic import BaseModel
from dotenv import load_dotenv
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import DocumentContentFormat
from azure.core.credentials import AzureKeyCredential
from openai import AzureOpenAI
from pdf2image import convert_from_path
from flask import Flask, request, render_template, flash, jsonify, send_file, redirect
from werkzeug.utils import secure_filename

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
    processing_method: str = "di_gpt_image"
):
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
        else:  # Either di_gpt_image or di_gpt_no_image
            # Initialize Document Intelligence client
            doc_client = DocumentIntelligenceClient(
                endpoint=doc_intelligence_endpoint,
                credential=AzureKeyCredential(doc_intelligence_key)
            )
            print(f"Using Document Intelligence with processing method: {processing_method}")

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
        if processing_method in ["di_gpt_image", "di_gpt_no_image"]:
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
        else:  # processing_method == "di_gpt_no_image"
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
        
        # Parse the response into our Pydantic model (same for both methods)
        parsed_result = response.choices[0].message.parsed
        
        # Print debug information about the result
        print(f"Result type: {type(parsed_result)}")
        print(f"Result has model_dump(): {hasattr(parsed_result, 'model_dump')}")
        print(f"Result has dict(): {hasattr(parsed_result, 'dict')}")
        print(f"Result model_dump(): {parsed_result.model_dump()}")
        
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
        
# Helper function to convert Pydantic models to DotDict
def serialize_model(obj):
    if hasattr(obj, 'model_dump'):
        data = obj.model_dump()
    elif hasattr(obj, 'dict'):
        data = obj.dict()
    elif isinstance(obj, list):
        return [serialize_model(item) for item in obj]
    elif isinstance(obj, dict):
        data = {k: serialize_model(v) for k, v in obj.items()}
    else:
        return obj
    
    if isinstance(data, dict):
        # Handle special keys to avoid conflict with dict methods
        if 'items' in data:
            data['line_items'] = data['items']
        
        # Ensure tax_amount is available as a field for backwards compatibility
        if 'total_tax_amount' in data and 'tax_amount' not in data:
            data['tax_amount'] = data['total_tax_amount']
        
        dot_dict = DotDict(data)
        # Convert nested dictionaries
        for key, value in data.items():
            if isinstance(value, dict):
                dot_dict.__dict__[key] = DotDict(value)
            elif isinstance(value, list):
                dot_dict.__dict__[key] = [serialize_model(item) if isinstance(item, (dict, list)) else item for item in value]
        return dot_dict
    return data

# Create uploads directory if it doesn't exist
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])



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
        # Convert to dict to make sure it's serializable for the template
        result_dict = serialize_model(result)
        
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
        print(f"Parsed result: {result_dict}")
        return render_template('index.html', 
                            result=result_dict, 
                            uploaded_file_path=file_path, 
                            debug_mode=False, 
                            uploaded_files=uploaded_files, 
                            model_definitions=None,
                            processing_complete=True)
    except Exception as e:
        import traceback
        print(f"Error processing file: {str(e)}")
        print(traceback.format_exc())
        flash(f'Error processing file: {str(e)}')
        return render_template('index.html', 
                            result=None,
                            uploaded_file_path=file_path, 
                            uploaded_files=uploaded_files,
                            debug_mode=False,
                            model_definitions=None)

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

if __name__ == "__main__":
    app.run(debug=True)

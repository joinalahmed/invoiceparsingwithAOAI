# Invoice Processing Application

## Overview
This application uses Azure Document Intelligence and Azure OpenAI services to automatically extract data from invoices. It provides a web-based interface for uploading invoices, selecting a processing method, and viewing the extracted information.

## Features
- Upload PDF invoices for processing
- Select from multiple processing methods:
  - DI Parse + GPT-4o with Image (combines Document Intelligence with GPT-4o vision capabilities)
  - DI Parse + GPT-4o (No Image) (combines Document Intelligence with GPT-4o text capabilities)
  - GPT-4o with Image Only (uses only GPT-4o vision capabilities)
- Interactive UI with real-time feedback
- Display of extracted invoice data in a structured format

## Setup and Installation

### Prerequisites
- Python 3.8 or higher
- Azure Document Intelligence service
- Azure OpenAI service with GPT-4o deployment

### Installation Steps
1. Clone the repository
2. Install required dependencies:
   ```
   pip install -r requirements.txt
   ```
3. Configure environment variables by creating a `.env` file with the following content:
   ```
   # Azure Document Intelligence Settings
   DOC_INTELLIGENCE_ENDPOINT=<your-document-intelligence-endpoint>
   DOC_INTELLIGENCE_KEY=<your-document-intelligence-key>
   
   # Azure OpenAI Settings
   OPENAI_ENDPOINT=<your-openai-endpoint>
   OPENAI_KEY=<your-openai-key>
   DEPLOYMENT_NAME=<your-openai-deployment-name>
   
   # OpenAI Library Expected Variables
   AZURE_OPENAI_API_KEY=<your-openai-key>
   AZURE_OPENAI_ENDPOINT=<your-openai-endpoint>
   ```

### Running the Application
Run the application using:
```
python app.py
```
The application will be accessible at http://localhost:5000 in your web browser.

## Usage
1. Open the application in your browser
2. Upload an invoice PDF using the "Upload Document" button
3. Select a processing method from the dropdown
4. Click "Run Analysis" to process the invoice
5. View the extracted information displayed on the page

## Notes
- The application stores uploaded files in the `uploads` directory
- Processed results are cached to improve performance
- The application validates that a processing method is selected before analysis

## Screenshots

### Main Application Interface
![Main Application Interface](static/screens/1.png)

### Processing Method Selection Dropdown
![Processing Method Selection](static/screens/2.png)

## Troubleshooting
- If you encounter environment variable errors, ensure your `.env` file contains all required variables
- For PDF rendering issues, ensure you have the necessary system dependencies for pdf2image
- Check application logs for detailed error information

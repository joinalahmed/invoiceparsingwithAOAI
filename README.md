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
3. Configure your environment variables:
   
   a. Copy the provided `.env.sample` file to create your own `.env` file:
   ```
   cp .env.sample .env
   ```
   
   b. Open the `.env` file in a text editor and replace the empty quotes with your actual API keys and endpoints:
   ```
   # Azure Document Intelligence Settings
   DOC_INTELLIGENCE_ENDPOINT="https://your-doc-intelligence-resource.cognitiveservices.azure.com/"
   DOC_INTELLIGENCE_KEY="your-doc-intelligence-key"
   
   # Azure OpenAI Settings
   OPENAI_ENDPOINT="https://your-openai-resource.openai.azure.com"
   OPENAI_KEY="your-openai-key"
   DEPLOYMENT_NAME="gpt-4o"
   
   # OpenAI Library Expected Variables
   AZURE_OPENAI_API_KEY="your-openai-key"
   AZURE_OPENAI_ENDPOINT="https://your-openai-resource.openai.azure.com"
   ```
   
   c. Note that `AZURE_OPENAI_API_KEY` should be the same as `OPENAI_KEY` and `AZURE_OPENAI_ENDPOINT` should be the same as `OPENAI_ENDPOINT`. These duplicated variables are needed due to the way the OpenAI library looks for environment variables.

### Required Files
The following files are necessary for running the application:

1. **app.py** - The main Flask application file that contains the server logic
2. **.env** - Environment variables file containing your API keys and endpoints
3. **.env.sample** - Template file with the structure for your .env file
4. **templates/index.html** - The HTML template for the web interface
5. **requirements.txt** - Lists all Python dependencies
6. **static/** - Directory for CSS, JavaScript, and static assets including screenshots
7. **uploads/** - Directory where uploaded invoices are stored

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

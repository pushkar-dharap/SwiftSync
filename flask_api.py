# flask_api.py
from flask import Flask, request, jsonify, send_from_directory, send_file
from flask_cors import CORS
from werkzeug.utils import secure_filename
import os
import uuid
import logging
from perfect4 import extract_invoice_data, analyze_excel_structure, classify_invoice_with_claude, update_excel_with_data
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Configuration
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload size
app.config['UPLOAD_FOLDER'] = os.environ.get('UPLOAD_FOLDER', 'uploads')
app.config['ALLOWED_EXTENSIONS'] = {'pdf', 'xlsx', 'xls'}

# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({"status": "healthy"}), 200

@app.route('/process', methods=['POST'])
def process_invoice():
    pdf_file = request.files.get('pdf')
    excel_file = request.files.get('excel')
    sheet_name = request.form.get('sheet_name', 'COA i-Kcal')

    if not pdf_file or not excel_file:
        return jsonify({"error": "Both PDF and Excel files are required."}), 400
        
    if not (allowed_file(pdf_file.filename) and allowed_file(excel_file.filename)):
        return jsonify({"error": "Invalid file type. Only PDF and Excel files are allowed."}), 400

    try:
        # Save uploaded files
        try:
            # Generate secure filenames
            pdf_filename = secure_filename(f"{uuid.uuid4()}_{pdf_file.filename}")
            excel_filename = secure_filename(f"{uuid.uuid4()}_{excel_file.filename}")
            pdf_path = os.path.join(app.config['UPLOAD_FOLDER'], pdf_filename)
            excel_path = os.path.join(app.config['UPLOAD_FOLDER'], excel_filename)

            # Save files
            pdf_file.save(pdf_path)
            excel_file.save(excel_path)
            
            logger.info(f"Saved files: {pdf_filename}, {excel_filename}")
        except Exception as e:
            logger.error(f"Error saving files: {str(e)}")
            return jsonify({"error": "Error saving uploaded files"}), 500

        # Extract data
        try:
            invoice_text = extract_invoice_data(pdf_path)
            coa_sheet, structure = analyze_excel_structure(excel_path, sheet_name=sheet_name)
            
            # Get API key from environment
            api_key = os.getenv("ANTHROPIC_API_KEY")
            if not api_key or api_key == 'your_anthropic_api_key_here':
                raise ValueError("Anthropic API key is not properly configured. Please set the ANTHROPIC_API_KEY environment variable.")
                
            classified_data = classify_invoice_with_claude(invoice_text, coa_sheet, structure, api_key)
            output_path = update_excel_with_data(excel_path, sheet_name, classified_data)
        except Exception as e:
            # Clean up files if they exist
            for file_path in [pdf_path, excel_path]:
                try:
                    if os.path.exists(file_path):
                        os.remove(file_path)
                except Exception as cleanup_error:
                    logger.warning(f"Could not clean up file {file_path}: {str(cleanup_error)}")
            raise  # Re-raise the original exception

        # Clean up uploaded files after processing
        try:
            if os.path.exists(pdf_path):
                os.remove(pdf_path)
            if os.path.exists(excel_path):
                os.remove(excel_path)
            logger.info("Cleaned up temporary files")
        except Exception as e:
            logger.warning(f"Warning: Could not clean up temporary files: {str(e)}")
            
        # Generate a URL for downloading the result
        download_url = f"/download/{os.path.basename(output_path)}"
        
        return jsonify({
            "status": "success",
            "message": "Processing completed successfully",
            "output_file": os.path.basename(output_path),
            "download_url": download_url
        })

    except Exception as e:
        logger.error(f"Error processing request: {str(e)}", exc_info=True)
        return jsonify({"error": "An error occurred while processing your request"}), 500

@app.route('/download/<filename>', methods=['GET'])
def download_file(filename):
    """
    Serve processed files for download
    """
    try:
        # Validate filename to prevent directory traversal
        if '..' in filename or filename.startswith('/'):
            return jsonify({"error": "Invalid filename"}), 400
            
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        
        # Check if file exists and is a file (not a directory)
        if not os.path.isfile(file_path):
            return jsonify({"error": "File not found"}), 404
            
        # Set appropriate headers for file download
        return send_file(
            file_path,
            as_attachment=True,
            download_name=filename,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
    except Exception as e:
        logger.error(f"Error downloading file {filename}: {str(e)}", exc_info=True)
        return jsonify({"error": "Error downloading file"}), 500

if __name__ == '__main__':
    # This is only used when running locally
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)

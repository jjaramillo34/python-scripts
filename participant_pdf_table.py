from fpdf import FPDF
import csv
from pathlib import Path
from PIL import Image
import unicodedata

def clean_text_for_pdf(text):
    """Clean text to remove problematic Unicode characters for PDF generation"""
    if not text:
        return ""
    
    # Convert to string and strip
    text = str(text).strip()
    
    # Replace common problematic characters
    replacements = {
        ''': "'",  # Right single quotation mark
        ''': "'",  # Left single quotation mark
        '"': '"',  # Left double quotation mark
        '"': '"',  # Right double quotation mark
        '–': '-',  # En dash
        '—': '-',  # Em dash
        '…': '...',  # Horizontal ellipsis
        '→': '->',  # Rightwards arrow
        '←': '<-',  # Leftwards arrow
        '↔': '<->',  # Left right arrow
        '✓': 'v',  # Check mark
        '✗': 'x',  # Ballot X
        '•': '*',  # Bullet
        '°': 'deg',  # Degree sign
        '±': '+/-',  # Plus-minus sign
    }
    
    for old, new in replacements.items():
        text = text.replace(old, new)
    
    # Normalize Unicode and remove any remaining problematic characters
    text = unicodedata.normalize('NFKD', text)
    
    # Remove any remaining non-ASCII characters that might cause issues
    text = ''.join(char for char in text if ord(char) < 128 or char in 'àáâãäåæçèéêëìíîïðñòóôõöøùúûüýþÿ')
    
    return text

class CancerAwarenessPDF(FPDF):
    def __init__(self):
        super().__init__()
        # Cancer awareness colors
        self.colors = {
            'teal': (0, 128, 128),      # Teal
            'pink': (255, 192, 203),    # Pink
            'light_green': (144, 238, 144),  # Light green
            'dark_green': (0, 100, 0),  # Dark green
            'white': (255, 255, 255),
            'black': (0, 0, 0),
            'light_gray': (240, 240, 240),
            'header_teal': (0, 139, 139),  # Darker teal for header
            'accent_pink': (255, 105, 180)  # Hot pink for accents
        }
    
    def header(self):
        # Header background with gradient effect using teal
        self.set_fill_color(*self.colors['header_teal'])
        self.rect(0, 0, 210, 40, 'F')
        
        # Add logo if it exists
        logo_path = Path("MetastaticBreastRibbon.png")
        if logo_path.exists():
            try:
                # Position logo on the left side
                self.image(str(logo_path), x=10, y=5, w=25, h=25)
            except Exception as e:
                print(f"Warning: Could not add logo: {e}")
        
        # Decorative line with pink accent
        self.set_draw_color(*self.colors['accent_pink'])
        self.set_line_width(2)
        self.line(10, 38, 200, 38)
        
        # Main title (adjusted for logo)
        self.set_font("Helvetica", "B", 24)
        self.set_text_color(*self.colors['white'])
        self.set_y(8)
        self.cell(0, 12, clean_text_for_pdf("2025 Fun Run Participants"), align="C")
        
        # Subtitle
        self.set_font("Helvetica", "I", 12)
        self.set_text_color(*self.colors['pink'])
        self.set_y(20)
        self.cell(0, 8, clean_text_for_pdf("Cancer Awareness Event"), align="C")
        self.ln(30)
    
    def footer(self):
        # Position at 15mm from bottom
        self.set_y(-15)
        
        # Decorative line with teal
        self.set_draw_color(*self.colors['teal'])
        self.set_line_width(1)
        self.line(10, self.get_y(), 200, self.get_y())
        
        # Page number with cancer awareness ribbon symbol
        self.set_font("Helvetica", "I", 10)
        self.set_text_color(*self.colors['teal'])
        self.cell(0, 10, f'Page {self.page_no()} | Cancer Awareness Event 2025', align='C')
    
    def create_table_header(self):
        """Create a styled table header"""
        # Header background
        self.set_fill_color(*self.colors['teal'])
        self.set_text_color(*self.colors['white'])
        self.set_font("Helvetica", "B", 11)
        
        # Column widths (adjusted for better fit)
        col_widths = [35, 35, 15, 50, 25]
        headers = ["Last Name", "First Name", "Age", "T-Shirt Size", "Quantity"]
        
        # Draw header cells
        for i, (header, width) in enumerate(zip(headers, col_widths)):
            self.cell(width, 10, header, border=1, fill=True, align='C')
        
        self.ln()
    
    def create_table_row(self, row_data, row_index):
        """Create a styled table row with alternating colors"""
        # Alternating row colors
        if row_index % 2 == 0:
            fill_color = self.colors['light_green']
            text_color = self.colors['black']
        else:
            fill_color = self.colors['pink']
            text_color = self.colors['black']
        
        self.set_fill_color(*fill_color)
        self.set_text_color(*text_color)
        self.set_font("Helvetica", "", 9)
        
        # Column widths (same as header)
        col_widths = [35, 35, 15, 50, 25]
        
        # Clean and format data
        cleaned_data = []
        for i, item in enumerate(row_data):
            if item is None or item == '' or str(item).strip() == '':
                cleaned_data.append('-')
            else:
                # Clean the text and limit length for better display
                cleaned = clean_text_for_pdf(str(item).strip())
                # Different truncation lengths for different columns
                max_lengths = [15, 15, 8, 25, 8]  # Last Name, First Name, Age, T-Shirt, Quantity
                if i < len(max_lengths) and len(cleaned) > max_lengths[i]:
                    cleaned = cleaned[:max_lengths[i]-3] + "..."
                cleaned_data.append(cleaned)
        
        # Draw row cells
        for i, (data, width) in enumerate(zip(cleaned_data, col_widths)):
            self.cell(width, 8, data, border=1, fill=True, align='C')
        
        self.ln()
    
    def add_summary_section(self, total_participants, tshirt_orders):
        """Add a summary section at the end"""
        self.ln(10)
        
        # Summary title
        self.set_font("Helvetica", "B", 14)
        self.set_text_color(*self.colors['dark_green'])
        self.cell(0, 8, "Event Summary", align='C')
        self.ln(8)
        
        # Summary box
        self.set_fill_color(*self.colors['light_gray'])
        self.set_draw_color(*self.colors['teal'])
        self.set_line_width(1)
        
        summary_text = f"Total Participants: {total_participants}\nT-Shirt Orders: {tshirt_orders}"
        self.multi_cell(0, 8, summary_text, border=1, fill=True, align='C')
        self.ln(5)
        
        # Cancer awareness message
        self.set_font("Helvetica", "I", 10)
        self.set_text_color(*self.colors['teal'])
        awareness_text = "Thank you for supporting cancer awareness and research!"
        self.cell(0, 6, awareness_text, align='C')

def create_participant_pdf():
    """Main function to create the participant PDF table"""
    # Initialize PDF
    pdf = CancerAwarenessPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    
    # Read CSV data
    csv_path = Path("Participant List 2025.csv")
    
    if not csv_path.exists():
        print(f"Error: {csv_path} not found!")
        return
    
    participants = []
    tshirt_orders = 0
    
    with open(csv_path, 'r', encoding='utf-8-sig') as file:  # utf-8-sig handles BOM
        csv_reader = csv.DictReader(file)
        
        for row in csv_reader:
            participants.append([
                row.get('Last Name', '').strip(),
                row.get('First Name', '').strip(),
                row.get('Age', '').strip(),
                row.get('Fun Run T-Shirt', '').strip(),
                row.get('Fun Run T-Shirt (Quantity)', '').strip()
            ])
            
            # Count t-shirt orders
            quantity = row.get('Fun Run T-Shirt (Quantity)', '')
            if quantity and quantity.isdigit():
                tshirt_orders += int(quantity)
    
    # Create table header
    pdf.create_table_header()
    
    # Add table rows
    for i, participant in enumerate(participants):
        pdf.create_table_row(participant, i)
    
    # Add summary section
    pdf.add_summary_section(len(participants), tshirt_orders)
    
    # Save the PDF
    output_path = Path("2025_Participant_List_Cancer_Awareness.pdf")
    pdf.output(str(output_path))
    print(f"PDF created successfully: {output_path}")
    print(f"Total participants: {len(participants)}")
    print(f"Total t-shirt orders: {tshirt_orders}")

if __name__ == "__main__":
    create_participant_pdf()

from fpdf import FPDF
from pathlib import Path
import re

def clean_text(text):
    """Remove or replace problematic Unicode characters"""
    # Replace box-drawing characters with ASCII equivalents
    replacements = {
        '┌': '+', '┐': '+', '└': '+', '┘': '+',
        '│': '|', '─': '-', '├': '+', '┤': '+',
        '┬': '+', '┴': '+', '┼': '+', '━': '=',
        '┃': '|', '┏': '+', '┓': '+', '┗': '+', '┛': '+',
        ''': "'", ''': "'", '"': '"', '"': '"',
        '–': '-', '—': '-', '…': '...',
        '→': '->', '←': '<-', '↔': '<->',
        '✓': 'v', '✗': 'x', '•': '*'
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    
    # Remove any remaining non-latin1 characters
    text = text.encode('latin-1', errors='ignore').decode('latin-1')
    return text

# Define a class for structured PDF formatting
class ArchitecturePDF(FPDF):
    def header(self):
        # Add a gradient-like header background
        self.set_fill_color(0, 51, 102)  # Dark blue
        self.rect(0, 0, 210, 30, 'F')
        
        # Add decorative line
        self.set_draw_color(255, 165, 0)  # Orange
        self.set_line_width(1)
        self.line(10, 28, 200, 28)
        
        # Title
        self.set_font("Helvetica", "B", 20)
        self.set_text_color(255, 255, 255)  # White
        self.set_y(10)
        self.cell(0, 10, "D79 LMS - Application Architecture", align="C")
        
        # Subtitle
        self.set_font("Helvetica", "I", 10)
        self.set_text_color(255, 165, 0)  # Orange
        self.set_y(20)
        self.cell(0, 5, "Technical Documentation", align="C")
        self.ln(20)

    def footer(self):
        # Position at 15mm from bottom
        self.set_y(-15)
        
        # Add decorative line
        self.set_draw_color(0, 51, 102)
        self.set_line_width(0.5)
        self.line(10, self.get_y(), 200, self.get_y())
        
        # Page number
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(128, 128, 128)
        self.cell(0, 10, f'Page {self.page_no()}', align='C')

    def chapter_title(self, title):
        # Chapter title with colored background
        self.set_fill_color(0, 102, 204)  # Medium blue
        self.set_text_color(255, 255, 255)  # White text
        self.set_font("Helvetica", "B", 16)
        
        # Add some padding and border radius effect
        self.set_draw_color(0, 51, 102)
        self.set_line_width(0.5)
        self.cell(0, 12, clean_text(title), border=1, fill=True, align='L')
        self.ln(15)

    def section_title(self, title):
        # Section title with left border accent
        self.set_draw_color(255, 165, 0)  # Orange
        self.set_line_width(3)
        x_pos = self.get_x()
        y_pos = self.get_y()
        
        # Draw accent line
        self.line(x_pos, y_pos, x_pos, y_pos + 8)
        
        # Title text
        self.set_x(x_pos + 5)
        self.set_font("Helvetica", "B", 13)
        self.set_text_color(0, 51, 102)
        self.multi_cell(0, 8, clean_text(title))
        self.ln(3)

    def body_text(self, text):
        if not text or not text.strip():
            return
        
        self.set_font("Helvetica", "", 10)
        self.set_text_color(40, 40, 40)
        
        # Add slight indentation for body text
        left_margin = self.l_margin
        self.set_left_margin(left_margin + 5)
        self.multi_cell(0, 6, clean_text(text))
        self.set_left_margin(left_margin)
        self.ln(2)

    def code_block(self, code):
        if not code or not code.strip():
            return
            
        # Code block with styled border and background
        self.set_font("Courier", "", 9)
        self.set_text_color(0, 100, 0)  # Dark green for code
        
        # Gradient-like background (light green to light gray)
        self.set_fill_color(240, 248, 255)  # Alice blue
        self.set_draw_color(70, 130, 180)  # Steel blue border
        self.set_line_width(0.3)
        
        # Add some padding
        left_margin = self.l_margin
        self.set_left_margin(left_margin + 3)
        self.multi_cell(0, 5, clean_text(code), border=1, fill=True)
        self.set_left_margin(left_margin)
        self.ln(4)
    
    def info_box(self, text, box_type="info"):
        """Add a colored info box for important information"""
        colors = {
            "info": (33, 150, 243, 227, 242, 253),    # Blue
            "warning": (255, 152, 0, 255, 243, 224),  # Orange
            "success": (76, 175, 80, 232, 245, 233),  # Green
            "error": (244, 67, 54, 255, 235, 238)     # Red
        }
        
        border_color, bg_color = colors.get(box_type, colors["info"])
        
        self.set_draw_color(*border_color[:3])
        self.set_fill_color(*bg_color[:3])
        self.set_text_color(*border_color[:3])
        self.set_font("Helvetica", "B", 10)
        self.set_line_width(1)
        
        self.multi_cell(0, 8, clean_text(text), border=1, fill=True)
        self.ln(3)

# Load markdown file
md_path = Path("d79_architecture.md")
markdown_content = md_path.read_text()

# Initialize PDF
pdf = ArchitecturePDF()
pdf.set_auto_page_break(auto=True, margin=15)
pdf.add_page()

# Split sections by horizontal rules
sections = re.split(r"\n---+\n", markdown_content)

for section in sections:
    # Extract and format titles
    title_match = re.search(r"^##+ (.+)", section)
    if title_match:
        title = title_match.group(1).strip()
        pdf.chapter_title(title)

    # Split between code blocks and body text
    blocks = re.split(r"```", section)
    for i, block in enumerate(blocks):
        if i % 2 == 0:
            text = re.sub(r"^#+ .+", "", block)  # remove markdown headers
            pdf.body_text(text.strip())
        else:
            pdf.code_block(block.strip())

# Save the PDF
output_path = Path("D79_LMS_Architecture.pdf")
pdf.output(str(output_path))
print(f"PDF created: {output_path}")

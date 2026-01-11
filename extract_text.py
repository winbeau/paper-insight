import zipfile
import xml.etree.ElementTree as ET
import sys

docx_path = "docs/PaperInsight智能论文分析与科研洞察管理系统说明书.docx"

try:
    with zipfile.ZipFile(docx_path) as z:
        xml_content = z.read('word/document.xml')
        
    tree = ET.fromstring(xml_content)
    
    # Namespaces can be tricky, so let's just inspect tags
    # We want to iterate over paragraphs (w:p) and then runs/text (w:t)
    
    full_text = []
    
    for element in tree.iter():
        if element.tag.endswith('}p'): # Paragraph
            para_text = []
            for child in element.iter():
                if child.tag.endswith('}t') and child.text:
                    para_text.append(child.text)
            if para_text:
                full_text.append(''.join(para_text))
                
    print('\n'.join(full_text))

except Exception as e:
    print(f"Error: {e}")

from concurrent.futures import ThreadPoolExecutor, as_completed
from jinja2 import Template
import random
import os
import subprocess
import tempfile
import boto3
import base64
import io

from urllib.parse import urlparse
from PIL import Image
from tqdm import tqdm

from pdelfin.silver_data.renderpdf import render_pdf_to_base64png

session = boto3.Session(profile_name='s2')
s3_client = session.client('s3')


def process_entry(i, entry):
    # Randomly decide whether to display gold on the left or right
    if random.choice([True, False]):
        left_text, right_text = entry["gold_text"], entry["eval_text"]
        left_alignment, right_alignment = entry["alignment"], entry["alignment"]
        left_class, right_class = "gold", "eval"
    else:
        left_text, right_text = entry["eval_text"], entry["gold_text"]
        left_alignment, right_alignment = entry["alignment"], entry["alignment"]
        left_class, right_class = "eval", "gold"

    # Convert newlines to <p> tags for proper formatting
    left_text = "<p>" + left_text.replace("\n", "</p><p>") + "</p>"
    right_text = "<p>" + right_text.replace("\n", "</p><p>") + "</p>"

    parsed_url = urlparse(entry["s3_path"])
    bucket = parsed_url.netloc
    s3_key = parsed_url.path.lstrip('/')
    signed_pdf_link = s3_client.generate_presigned_url("get_object", Params={"Bucket": bucket, "Key": s3_key}, ExpiresIn=604800)

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_pdf:
        pdf_path = tmp_pdf.name
        bucket, key = entry["s3_path"].replace("s3://", "").split('/', 1)
        s3_client.download_file(bucket, key, pdf_path)
        
        page_image_base64 = render_pdf_to_base64png(tmp_pdf.name, entry["page"], target_longest_image_dim=1024)

    return {
        "entry_id": i,
        "page_image": page_image_base64,
        "s3_path": entry["s3_path"],
        "page": entry["page"],
        "signed_pdf_link": signed_pdf_link,
        "left_text": left_text,
        "right_text": right_text,
        "left_alignment": left_alignment,
        "right_alignment": right_alignment,
        "left_class": left_class,
        "right_class": right_class,
        "gold_class": "gold" if left_class == "gold" else "eval",
        "eval_class": "eval" if right_class == "eval" else "gold"
    }


def create_review_html(data, filename="review_page.html"):
    # Load the Jinja2 template from the file
    with open(os.path.join(os.path.dirname(__file__), "evalhtml_template.html"), "r") as f:
        template = Template(f.read())

    entries = []
    with ThreadPoolExecutor() as executor:
        # Submit tasks to the executor
        futures = [executor.submit(process_entry, i, entry) for i, entry in enumerate(data)]

        # Process the results as they are completed
        for future in tqdm(futures):
            entries.append(future.result())

    # Render the template with the entries
    final_html = template.render(entries=entries)

    # Write the HTML content to the specified file
    with open(filename, "w") as f:
        f.write(final_html)

    print(f"HTML file '{filename}' created successfully!")

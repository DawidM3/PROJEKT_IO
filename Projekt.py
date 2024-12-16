from flask import Flask, render_template, request, jsonify, send_file
import requests
from bs4 import BeautifulSoup
import threading
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse, urljoin
from datetime import datetime
import re
import pandas as pd
import os

app = Flask(__name__)

crawl_results = []
crawl_logs = []
is_crawling = False  # Flag to control the crawling process


executor = ThreadPoolExecutor(max_workers=5)


def get_sitemap_from_robots(url):
    sitemap_urls = []
    try:
        robots_url = urljoin(url, "/robots.txt")
        response = requests.get(robots_url, timeout=5)
        if response.status_code == 200:
            log_message(f"Accessing {robots_url} for sitemaps", "info")
            sitemap_lines = re.findall(r'Sitemap: (.+)', response.text)
            sitemap_urls = [line.strip() for line in sitemap_lines]
            log_message(f"Found sitemaps: {', '.join(sitemap_urls)}", "success")
        else:
            log_message(f"No robots.txt or failed to access {robots_url}", "error")
    except Exception as e:
        log_message(f"Error accessing robots.txt for {url}: {str(e)}", "error")
    
    return sitemap_urls


def extract_urls_from_sitemap(sitemap_url):
    urls = []
    try:
        response = requests.get(sitemap_url, timeout=5)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'xml')
            urls = [loc.get_text() for loc in soup.find_all('loc')]
            log_message(f"Extracted {len(urls)} URLs from sitemap: {sitemap_url}", "success")
        else:
            log_message(f"Failed to retrieve sitemap {sitemap_url}: Status code {response.status_code}", "error")
    except Exception as e:
        log_message(f"Error processing sitemap {sitemap_url}: {str(e)}", "error")
    
    return urls


def extract_data_from_url(session, url):
    try:
        response = session.get(url, timeout=5)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')

           
            meta_title = soup.find('title').get_text(strip=True) if soup.find('title') else 'No title found'
            log_message(f"Meta title found for {url}: {meta_title}", "success")

           
            meta_description = soup.find('meta', attrs={'name': 'description'})
            if meta_description:
                meta_description = meta_description['content']
            else:
                meta_description = 'No description found'
            log_message(f"Meta description found for {url}: {meta_description}", "info")

            
            p_tags_content = [p.get_text(strip=True) for p in soup.find_all('p')]
            log_message(f"P tags content extracted for {url}", "info")

            return {
                'url': url,
                'meta_title': meta_title,
                'meta_description': meta_description,
                'p_tags': ' '.join(p_tags_content)  # Combine <p> contents as a single string
            }
        else:
            log_message(f"Failed to retrieve {url}: Status code {response.status_code}", "error")
            return None
    except Exception as e:
        log_message(f"Error processing {url}: {str(e)}", "error")
        return None


def log_message(message, log_type):
    timestamp = datetime.now().strftime('%H:%M:%S')
    color_class = log_type  # Define log type as class for color
    formatted_message = f"<span class='{color_class}'>{timestamp} - {message}</span>"
    crawl_logs.append(formatted_message)
    print(formatted_message)


def crawl_and_collect_data(start_url, max_pages=100):
    global is_crawling
    is_crawling = True

    parsed_start_url = urlparse(start_url)
    base_domain = parsed_start_url.netloc
    urls_to_crawl = [start_url]
    crawled_urls = set()
    sitemap_urls_set = set()  # Set to store sitemap URLs

   
    excluded_extensions = {'.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp'}

    
    sitemaps = get_sitemap_from_robots(start_url)
    for sitemap in sitemaps:
        urls_from_sitemap = extract_urls_from_sitemap(sitemap)
        urls_to_crawl.extend(urls_from_sitemap)
        sitemap_urls_set.update(urls_from_sitemap)  # Add sitemap URLs to the set

    with requests.Session() as session:
        while urls_to_crawl and len(crawled_urls) < max_pages and is_crawling:
            current_url = urls_to_crawl.pop(0)
            if current_url in crawled_urls:
                continue

           
            if any(current_url.lower().endswith(ext) for ext in excluded_extensions):
                log_message(f"Skipping image or excluded file: {current_url}", "info")
                continue

            log_message(f"Crawling {current_url}", "info")
            crawled_urls.add(current_url)

          
            data = extract_data_from_url(session, current_url)
            if data and current_url not in sitemap_urls_set:  # Exclude sitemap URLs
                crawl_results.append(data)

               
                try:
                    for link in BeautifulSoup(session.get(current_url).text, 'html.parser').find_all('a', href=True):
                        new_url = urljoin(current_url, link['href'])
                        parsed_new_url = urlparse(new_url)

                       
                        if parsed_new_url.netloc == base_domain and new_url not in crawled_urls:
                            urls_to_crawl.append(new_url)
                except Exception as e:
                    log_message(f"Error processing links from {current_url}: {str(e)}", "error")
    is_crawling = False


@app.route('/')
def index():
    return render_template('Projekt.html')


@app.route('/start_crawl', methods=['POST'])
def start_crawl():
    start_url = request.form['start_url']
    global crawl_results, crawl_logs
    crawl_results.clear()
    crawl_logs.clear()

   
    threading.Thread(target=crawl_and_collect_data, args=(start_url,)).start()
    return jsonify({'message': 'Crawling started', 'logs': crawl_logs})


@app.route('/stop_crawl', methods=['POST'])
def stop_crawl():
    global is_crawling
    is_crawling = False
    return jsonify({'message': 'Crawling stopped'})


@app.route('/export_results', methods=['GET'])
def export_results():
    global crawl_results

   
    if not crawl_results or len(crawl_results) == 0:
        log_message("Brak danych do eksportu", "error")
        return jsonify({'message': 'Brak danych do eksportu'}), 400

    try:
       
        df = pd.DataFrame(crawl_results)

       
        if df.empty:
            log_message("DataFrame jest pusty - brak danych do zapisania", "error")
            return jsonify({'message': 'Brak danych do zapisania'}), 400

     
        file_path = os.path.join(os.getcwd(), 'crawl_results.xlsx')

      
        if os.path.exists(file_path):
            os.remove(file_path)

        
        df.to_excel(file_path, index=False)

      
        log_message(f"Wyniki zostały wyeksportowane do pliku: {file_path}", "success")

       
        return send_file(
            file_path,
            as_attachment=True,
            download_name='crawl_results.xlsx',
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
    except ValueError as ve:
        log_message(f"Błąd wartości podczas eksportu: {str(ve)}", "error")
        return jsonify({'message': f'Błąd danych: {str(ve)}'}), 500
    except PermissionError as pe:
        log_message(f"Błąd dostępu do pliku: {str(pe)}", "error")
        return jsonify({'message': f'Błąd dostępu do pliku: {str(pe)}'}), 500
    except Exception as e:
        log_message(f"Nieoczekiwany błąd podczas eksportu: {str(e)}", "error")
        return jsonify({'message': f'Nieoczekiwany błąd: {str(e)}'}), 500


@app.route('/get_logs', methods=['GET'])
def get_logs():
    return jsonify({'logs': crawl_logs})


@app.route('/get_results', methods=['GET'])
def get_results():
    return jsonify({'results': crawl_results})

if __name__ == '__main__':
    app.run(debug=True)

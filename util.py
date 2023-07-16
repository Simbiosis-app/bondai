# from requests_html import HTMLSession
import requests
from bs4 import BeautifulSoup

REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3"
}

def get_website_html(url):
        response = requests.get(url, headers=REQUEST_HEADERS, timeout=10)
        return response.text
        

# def get_website_html(url):
#         session = HTMLSession()
#         response = session.get(url, headers=REQUEST_HEADERS, timeout=10)
#         try:
#                 response.html.render()
#         except Exception:
#                 pass
#         return response.html.raw_html

def get_website_text(url):
        html = get_website_html(url)
        soup = BeautifulSoup(html, "html.parser")
        return soup.get_text()

def get_website_links(url):
        html = get_website_html(url)
        soup = BeautifulSoup(html, "html.parser")
        return soup.find_all("a")
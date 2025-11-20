import streamlit as st
import requests
from bs4 import BeautifulSoup
import anthropic

st.set_page_config(page_title="BHF Docs Q&A", page_icon="🫀")

st.title("🫀 BHF Documentation Q&A")
st.write("Ask questions about BHF Data Science Centre documentation")

# API Key input
api_key = st.text_input("Anthropic API Key", type="password", placeholder="sk-ant-...")

if not api_key:
    st.warning("Please enter your Anthropic API key to continue")
    st.stop()

# Function to scrape entire BHF docs website
@st.cache_data(ttl=3600)  # Cache for 1 hour
def scrape_bhf_docs():
    base_url = "https://bhfdsc.github.io/documentation/"
    all_content = []
    visited_urls = set()
    
    def scrape_page(url):
        if url in visited_urls:
            return ""
        visited_urls.add(url)
        
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Get main content
            main_content = soup.find('main') or soup.find('body')
            if main_content:
                # Remove script and style elements
                for element in main_content(['script', 'style']):
                    element.decompose()
                text = main_content.get_text()
                # Clean up whitespace
                text = ' '.join(text.split())
                return text
            return ""
        except Exception as e:
            st.warning(f"Could not scrape {url}: {e}")
            return ""
    
    try:
        # Get main page first
        progress_bar = st.progress(0)
        st.write("Scraping main page...")
        
        response = requests.get(base_url, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Add main page content
        main_content = scrape_page(base_url)
        if main_content:
            all_content.append(main_content)
        
        # Find all internal links
        links = soup.find_all('a', href=True)
        internal_links = []
        
        for link in links:
            href = link['href']
            # Make absolute URL
            if href.startswith('/'):
                full_url = "https://bhfdsc.github.io" + href
            elif href.startswith('http'):
                full_url = href
            else:
                full_url = base_url.rstrip('/') + '/' + href
            
            # Only include BHF documentation links
            if "bhfdsc.github.io/documentation" in full_url and full_url not in visited_urls:
                internal_links.append(full_url)
        
        # Remove duplicates
        internal_links = list(set(internal_links))
        
        st.write(f"Found {len(internal_links)} pages to scrape...")
        
        # Scrape each page
        for i, url in enumerate(internal_links):
            progress_bar.progress((i + 1) / len(internal_links))
            st.write(f"Scraping: {url}")
            
            page_content = scrape_page(url)
            if page_content:
                all_content.append(page_content)
        
        progress_bar.empty()
        return " ".join(all_content)
        
    except Exception as e:
        st.error(f"Failed to scrape documentation: {e}")
        return ""

# Load documentation
with st.spinner("Scraping entire BHF documentation website..."):
    docs_content = scrape_bhf_docs()

if not docs_content:
    st.error("Could not load documentation content")
    st.stop()

st.success(f"Successfully scraped entire BHF documentation website! Loaded {len(docs_content):,} characters total.")

# Question input
question = st.text_area(
    "Your question:",
    placeholder="e.g., How do I access CVD-COVID-UK data?",
    height=100
)

if st.button("Ask Question", type="primary") and question:
    with st.spinner("Getting answer..."):
        try:
            client = anthropic.Anthropic(api_key=api_key)
            
            prompt = f"""Based on the BHF Data Science Centre documentation below, please answer the user's question.

Documentation:
{docs_content}

Question: {question}

Please provide a helpful answer based on the documentation. If the information isn't available in the documentation, say so clearly."""

            message = client.messages.create(
                model="claude-opus-4-1",
                max_tokens=1000,
                messages=[{"role": "user", "content": prompt}]
            )
            
            st.markdown("### Answer:")
            st.write(message.content[0].text)
            
        except Exception as e:
            st.error(f"Error: {e}")

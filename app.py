import streamlit as st
import requests
from bs4 import BeautifulSoup
import anthropic

st.set_page_config(page_title="BHF Docs Q&A", page_icon="🫀")

st.title("🫀 BHF Documentation Q&A")
st.write("Ask questions about BHF Data Science Centre documentation")

# API Key - try secrets first, then user input
api_key = None

# Try to get API key from secrets
try:
    api_key = st.secrets["ANTHROPIC_API_KEY"]
    st.success("✅ API key loaded from secrets")
except:
    # Fall back to manual input
    api_key = st.text_input("Anthropic API Key", type="password", placeholder="sk-ant-...")
    
    if not api_key:
        st.warning("Please enter your Anthropic API key to continue")
        st.info("💡 **For Streamlit Cloud:** Add your API key to secrets as `ANTHROPIC_API_KEY`")
        st.stop()

# Function to scrape entire BHF docs website
@st.cache_data(ttl=3600)  # Cache for 1 hour
def scrape_bhf_docs():
    base_url = "https://bhfdsc.github.io/documentation/"
    all_content = []
    visited_urls = set()
    
    def scrape_page(url):
        if url in visited_urls:
            return None
        visited_urls.add(url)
        
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Get page title
            title = soup.find('title')
            page_title = title.get_text().strip() if title else url.split('/')[-1]
            
            # Get main content
            main_content = soup.find('main') or soup.find('body')
            if main_content:
                # Remove script and style elements
                for element in main_content(['script', 'style']):
                    element.decompose()
                text = main_content.get_text()
                # Clean up whitespace
                text = ' '.join(text.split())
                return {"title": page_title, "content": text, "url": url}
            return None
        except Exception:
            return None
    
    try:
        # Get main page first
        progress_bar = st.progress(0)
        
        response = requests.get(base_url, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Add main page content
        main_page = scrape_page(base_url)
        if main_page:
            all_content.append(main_page)
        
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
        
        # Scrape each page
        for i, url in enumerate(internal_links):
            progress_bar.progress((i + 1) / len(internal_links))
            
            page_data = scrape_page(url)
            if page_data:
                all_content.append(page_data)
        
        progress_bar.empty()
        
        # Return both structured data and combined text
        total_chars = sum(len(page["content"]) for page in all_content)
        return all_content, total_chars, len(all_content)
        
    except Exception as e:
        st.error(f"Failed to scrape documentation: {e}")
        return [], 0, 0

# Load documentation
with st.spinner("Scraping entire BHF documentation website..."):
    docs_pages, total_chars, total_pages = scrape_bhf_docs()

if not docs_pages:
    st.error("Could not load documentation content")
    st.stop()

st.success(f"Successfully scraped {total_pages} pages with {total_chars:,} total characters")

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
            
            # Build context with page sources
            context = ""
            for page in docs_pages:
                context += f"\n\n--- PAGE: {page['title']} ---\n"
                context += page['content']
            
            prompt = f"""Based on the BHF Data Science Centre documentation below, please answer the user's question.

When providing your answer, please cite which specific page(s) you got the information from by mentioning the page title(s).

Documentation:
{context}

Question: {question}

Please provide a helpful answer based on the documentation and clearly state which page(s) you found the information on. If the information isn't available in the documentation, say so clearly."""

            message = client.messages.create(
                model="claude-haiku-4-5",
                max_tokens=10000,
                messages=[{"role": "user", "content": prompt}]
            )
            
            st.markdown("### Answer:")
            st.write(message.content[0].text)
            
        except Exception as e:
            st.error(f"Error: {e}")

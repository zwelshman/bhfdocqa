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

# Simple function to scrape BHF docs
@st.cache_data(ttl=3600)  # Cache for 1 hour
def scrape_bhf_docs():
    base_url = "https://bhfdsc.github.io/documentation/"
    
    try:
        response = requests.get(base_url, timeout=10)
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
        st.error(f"Failed to scrape documentation: {e}")
        return ""

# Load documentation
with st.spinner("Loading BHF documentation..."):
    docs_content = scrape_bhf_docs()

if not docs_content:
    st.error("Could not load documentation content")
    st.stop()

st.success(f"Loaded {len(docs_content):,} characters from BHF documentation")

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
                model="claude-sonnet-4-20250514",
                max_tokens=1000,
                messages=[{"role": "user", "content": prompt}]
            )
            
            st.markdown("### Answer:")
            st.write(message.content[0].text)
            
        except Exception as e:
            st.error(f"Error: {e}")

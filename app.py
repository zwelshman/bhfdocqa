import streamlit as st
import requests
from bs4 import BeautifulSoup
import anthropic
import time
from urllib.parse import urljoin, urlparse
import re
from typing import List, Dict, Set
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Page configuration
st.set_page_config(
    page_title="BHF DSC Documentation Q&A",
    page_icon="🫀",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for better styling
st.markdown("""
<style>
    .main-header {
        background: linear-gradient(90deg, #e74c3c, #c0392b);
        padding: 1rem;
        border-radius: 10px;
        color: white;
        margin-bottom: 2rem;
    }
    .chat-message {
        padding: 1rem;
        margin: 1rem 0;
        border-radius: 10px;
        border-left: 4px solid #3498db;
        background-color: #f8f9fa;
    }
    .user-message {
        background-color: #e3f2fd;
        border-left-color: #2196f3;
    }
    .assistant-message {
        background-color: #f3e5f5;
        border-left-color: #9c27b0;
    }
    .sidebar-content {
        background-color: #f8f9fa;
        padding: 1rem;
        border-radius: 10px;
        margin-bottom: 1rem;
    }
</style>
""", unsafe_allow_html=True)

class BHFDocumentationScraper:
    """Class to scrape and manage content from BHF DSC documentation website."""
    
    def __init__(self, base_url: str = "https://bhfdsc.github.io/documentation/"):
        self.base_url = base_url
        self.scraped_content: Dict[str, str] = {}
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
    
    def clean_text(self, text: str) -> str:
        """Clean and normalize text content."""
        # Remove extra whitespace and newlines
        text = re.sub(r'\s+', ' ', text)
        # Remove common HTML artifacts
        text = re.sub(r'\[.*?\]\(\)', '', text)  # Remove empty markdown links
        text = re.sub(r'!\[\]\(\)', '', text)   # Remove empty image placeholders
        return text.strip()
    
    def scrape_page(self, url: str) -> Dict[str, str]:
        """Scrape content from a single page."""
        try:
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Remove script and style elements
            for script in soup(["script", "style"]):
                script.decompose()
            
            # Extract title
            title = soup.find('title')
            title_text = title.get_text() if title else "Unknown"
            
            # Extract main content (try different content selectors)
            content_selectors = [
                'main', 'article', '[role="main"]', '.content', 
                '.main-content', '#content', '.post-content'
            ]
            
            content_text = ""
            for selector in content_selectors:
                content = soup.select_one(selector)
                if content:
                    content_text = content.get_text()
                    break
            
            # If no main content found, get body text
            if not content_text:
                body = soup.find('body')
                content_text = body.get_text() if body else soup.get_text()
            
            # Clean the text
            content_text = self.clean_text(content_text)
            
            return {
                'title': title_text,
                'content': content_text,
                'url': url
            }
            
        except Exception as e:
            logger.error(f"Error scraping {url}: {str(e)}")
            return {
                'title': "Error",
                'content': f"Error scraping content: {str(e)}",
                'url': url
            }
    
    def discover_pages(self) -> List[str]:
        """Discover available pages on the documentation site."""
        pages = [self.base_url]
        
        # Common documentation page patterns
        common_paths = [
            'guides/', 'docs/', 'tools/', 'resources/', 'about/',
            'datasets/', 'coverage_plot/', 'team/', 'contact/',
            'docs/dataset_overview/', 'docs/dataset_overview/coverage_plot/'
        ]
        
        for path in common_paths:
            full_url = urljoin(self.base_url, path)
            pages.append(full_url)
        
        return pages
    
    def scrape_all_content(self) -> Dict[str, Dict[str, str]]:
        """Scrape content from all discoverable pages."""
        pages = self.discover_pages()
        all_content = {}
        
        for url in pages:
            try:
                content = self.scrape_page(url)
                if content['content'] and len(content['content']) > 100:  # Only keep substantial content
                    all_content[url] = content
                    time.sleep(0.5)  # Be respectful with requests
            except Exception as e:
                logger.error(f"Failed to scrape {url}: {str(e)}")
                continue
        
        self.scraped_content = all_content
        return all_content

class BHFDocumentationQA:
    """Class to handle Q&A functionality using Anthropic API."""
    
    def __init__(self, api_key: str):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.content_database: Dict[str, Dict[str, str]] = {}
    
    def load_content(self, content: Dict[str, Dict[str, str]]):
        """Load scraped content into the Q&A system."""
        self.content_database = content
    
    def search_relevant_content(self, query: str, max_results: int = 3) -> str:
        """Search for relevant content based on the query."""
        query_lower = query.lower()
        relevant_content = []
        
        for url, content in self.content_database.items():
            # Simple relevance scoring based on keyword matches
            content_lower = content['content'].lower()
            title_lower = content['title'].lower()
            
            # Score based on keyword matches in title and content
            score = 0
            query_words = query_lower.split()
            
            for word in query_words:
                if len(word) > 2:  # Ignore very short words
                    score += title_lower.count(word) * 3  # Title matches weighted higher
                    score += content_lower.count(word)
            
            if score > 0:
                relevant_content.append((score, url, content))
        
        # Sort by relevance score and take top results
        relevant_content.sort(key=lambda x: x[0], reverse=True)
        
        # Compile relevant content into a single string
        context = ""
        for i, (score, url, content) in enumerate(relevant_content[:max_results]):
            context += f"\n--- Source: {content['title']} ({url}) ---\n"
            # Truncate very long content
            content_text = content['content']
            if len(content_text) > 2000:
                content_text = content_text[:2000] + "... [content truncated]"
            context += content_text + "\n"
        
        return context
    
    def answer_question(self, question: str) -> str:
        """Answer a question using the Anthropic API and scraped content."""
        try:
            # Search for relevant content
            relevant_content = self.search_relevant_content(question)
            
            if not relevant_content.strip():
                return "I couldn't find relevant information in the BHF Data Science Centre documentation to answer your question. Please try asking about topics related to CVD-COVID-UK, COVID-IMPACT, datasets, or research tools."
            
            # Create the prompt
            prompt = f"""You are an assistant helping users understand the BHF Data Science Centre documentation and research programmes. Use the provided content from the BHF DSC documentation website to answer the user's question.

Relevant content from BHF DSC documentation:
{relevant_content}

User question: {question}

Please provide a helpful, accurate answer based on the documentation content above. If the documentation doesn't contain enough information to fully answer the question, say so clearly and suggest where the user might find more information (such as contacting bhfdsc_hds@hdruk.ac.uk).

Focus on:
- CVD-COVID-UK and COVID-IMPACT research programmes
- Available datasets and their coverage
- Tools and resources for researchers
- Data access procedures
- Team information and contacts

Answer:"""

            # Make the API call
            message = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1000,
                messages=[{
                    "role": "user",
                    "content": prompt
                }]
            )
            
            return message.content[0].text
            
        except Exception as e:
            logger.error(f"Error in answer_question: {str(e)}")
            return f"I encountered an error while processing your question: {str(e)}. Please try again or contact the BHF Data Science Centre directly."

def main():
    """Main Streamlit application."""
    
    # Header
    st.markdown("""
    <div class="main-header">
        <h1>🫀 BHF Data Science Centre Documentation Q&A</h1>
        <p>Ask questions about the BHF DSC documentation, CVD-COVID-UK/COVID-IMPACT programmes, datasets, and research tools.</p>
    </div>
    """, unsafe_allow_html=True)
    
    # Sidebar for configuration and information
    with st.sidebar:
        st.markdown('<div class="sidebar-content">', unsafe_allow_html=True)
        st.header("Configuration")
        
        # API Key input
        api_key = st.text_input(
            "Anthropic API Key",
            type="password",
            help="Enter your Anthropic API key to enable Q&A functionality"
        )
        
        # Content refresh button
        if st.button("🔄 Refresh Documentation Content"):
            with st.spinner("Fetching latest documentation content..."):
                scraper = BHFDocumentationScraper()
                content = scraper.scrape_all_content()
                st.session_state['documentation_content'] = content
                st.success(f"Loaded content from {len(content)} pages")
        
        st.markdown("---")
        st.header("About")
        st.markdown("""
        This application allows you to ask questions about:
        
        - **CVD-COVID-UK/COVID-IMPACT** research programmes
        - **Available datasets** and their coverage
        - **Research tools** and resources
        - **Data access** procedures
        - **Team information** and contacts
        
        The system searches through the BHF Data Science Centre documentation website and provides answers using AI.
        """)
        
        st.markdown("---")
        st.info("💡 **Tip:** Try asking about specific datasets, research tools, or how to access data through the CVD-COVID-UK programme.")
        
        st.markdown('</div>', unsafe_allow_html=True)
    
    # Initialize session state
    if 'documentation_content' not in st.session_state:
        st.session_state['documentation_content'] = {}
    
    if 'conversation_history' not in st.session_state:
        st.session_state['conversation_history'] = []
    
    # Main content area
    if not api_key:
        st.warning("⚠️ Please enter your Anthropic API key in the sidebar to start asking questions.")
        st.stop()
    
    # Initialize Q&A system
    qa_system = BHFDocumentationQA(api_key)
    
    # Load content if available
    if not st.session_state['documentation_content']:
        with st.spinner("Loading BHF DSC documentation content..."):
            scraper = BHFDocumentationScraper()
            content = scraper.scrape_all_content()
            st.session_state['documentation_content'] = content
    
    qa_system.load_content(st.session_state['documentation_content'])
    
    # Display content summary
    if st.session_state['documentation_content']:
        st.success(f"✅ Loaded documentation from {len(st.session_state['documentation_content'])} pages")
    
    # Question input
    st.header("Ask a Question")
    question = st.text_input(
        "What would you like to know about the BHF Data Science Centre documentation?",
        placeholder="e.g., How do I access data through CVD-COVID-UK? What datasets are available? Who is on the team?"
    )
    
    col1, col2 = st.columns([1, 4])
    with col1:
        ask_button = st.button("🔍 Ask Question", type="primary")
    with col2:
        if st.button("🗑️ Clear Conversation"):
            st.session_state['conversation_history'] = []
            st.rerun()
    
    # Process question
    if ask_button and question:
        with st.spinner("Searching documentation and generating answer..."):
            answer = qa_system.answer_question(question)
            
            # Add to conversation history
            st.session_state['conversation_history'].append({
                'question': question,
                'answer': answer,
                'timestamp': time.time()
            })
    
    # Display conversation history
    if st.session_state['conversation_history']:
        st.header("Conversation History")
        
        for i, conversation in enumerate(reversed(st.session_state['conversation_history'])):
            with st.expander(f"Q: {conversation['question'][:100]}{'...' if len(conversation['question']) > 100 else ''}", expanded=i==0):
                st.markdown(f'<div class="chat-message user-message"><strong>Question:</strong> {conversation["question"]}</div>', unsafe_allow_html=True)
                st.markdown(f'<div class="chat-message assistant-message"><strong>Answer:</strong><br>{conversation["answer"]}</div>', unsafe_allow_html=True)
    
    # Footer
    st.markdown("---")
    st.markdown("""
    <div style="text-align: center; color: #666;">
        <p>Powered by BHF Data Science Centre Documentation | 
        <a href="https://bhfdsc.github.io/documentation/" target="_blank">Visit Documentation Site</a> | 
        <a href="mailto:bhfdsc_hds@hdruk.ac.uk">Contact Team</a></p>
    </div>
    """, unsafe_allow_html=True)

if __name__ == "__main__":
    main()

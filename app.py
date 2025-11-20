import streamlit as st
import requests
from bs4 import BeautifulSoup
import anthropic
import time
from urllib.parse import urljoin, urlparse
import re
import json
import tempfile
import os
from typing import List, Dict, Set, Optional, Tuple
import logging
from datetime import datetime, timedelta
from pathlib import Path

# Try to import configuration
try:
    from bhf_dsc_qa_config import SCRAPING, ANTHROPIC, SEARCH, UI, CONTACT, PROCESSING, LOGGING, CACHE
except ImportError:
    # Default configuration if config file not found
    SCRAPING = {
        "base_url": "https://bhfdsc.github.io/documentation/",
        "timeout": 10,
        "delay_between_requests": 0.5,
        "min_content_length": 100,
        "max_content_length": 10000,
    }
    ANTHROPIC = {"model": "claude-sonnet-4-20250514", "max_tokens": 1000, "max_context_sources": 3}
    SEARCH = {"title_weight": 3, "content_weight": 1, "min_word_length": 3, "max_results": 3}
    UI = {"page_title": "BHF DSC Documentation Q&A", "page_icon": "🫀", "layout": "wide"}
    CONTACT = {"team_email": "bhfdsc_hds@hdruk.ac.uk"}
    PROCESSING = {"remove_elements": ["script", "style"], "content_selectors": ["main", "article", "[role='main']"]}
    LOGGING = {"level": "INFO"}
    CACHE = {"enable_content_cache": True, "cache_expiry": 3600}

# Configure logging
logging.basicConfig(
    level=getattr(logging, LOGGING.get("level", "INFO")),
    format=LOGGING.get("format", "%(asctime)s - %(name)s - %(levelname)s - %(message)s")
)
logger = logging.getLogger(__name__)

# Page configuration
st.set_page_config(
    page_title=UI.get("page_title", "BHF DSC Documentation Q&A"),
    page_icon=UI.get("page_icon", "🫀"),
    layout=UI.get("layout", "wide"),
    initial_sidebar_state="expanded"
)

# Enhanced CSS styling
st.markdown("""
<style>
    .main-header {
        background: linear-gradient(135deg, #e74c3c, #c0392b);
        padding: 1.5rem;
        border-radius: 15px;
        color: white;
        margin-bottom: 2rem;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
    }
    .main-header h1 {
        margin: 0;
        font-size: 2.5rem;
        font-weight: 700;
    }
    .main-header p {
        margin: 0.5rem 0 0 0;
        font-size: 1.1rem;
        opacity: 0.9;
    }
    .chat-message {
        padding: 1.2rem;
        margin: 1rem 0;
        border-radius: 12px;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
    }
    .user-message {
        background: linear-gradient(135deg, #e3f2fd, #bbdefb);
        border-left: 4px solid #2196f3;
    }
    .assistant-message {
        background: linear-gradient(135deg, #f3e5f5, #e1bee7);
        border-left: 4px solid #9c27b0;
    }
    .sidebar-content {
        background-color: #f8f9fa;
        padding: 1.2rem;
        border-radius: 12px;
        margin-bottom: 1rem;
        border: 1px solid #e9ecef;
    }
    .status-indicator {
        padding: 0.5rem 1rem;
        border-radius: 8px;
        margin: 0.5rem 0;
        font-weight: 500;
    }
    .status-success {
        background-color: #d4edda;
        color: #155724;
        border: 1px solid #c3e6cb;
    }
    .status-warning {
        background-color: #fff3cd;
        color: #856404;
        border: 1px solid #ffeaa7;
    }
    .status-error {
        background-color: #f8d7da;
        color: #721c24;
        border: 1px solid #f5c6cb;
    }
    .content-stats {
        background: linear-gradient(135deg, #f8f9fa, #e9ecef);
        padding: 1rem;
        border-radius: 8px;
        margin: 1rem 0;
    }
    .question-suggestions {
        background: #f8f9fa;
        border-radius: 8px;
        padding: 1rem;
        margin: 1rem 0;
        border-left: 4px solid #17a2b8;
    }
</style>
""", unsafe_allow_html=True)

class EnhancedBHFDocumentationScraper:
    """Enhanced version of the BHF Documentation Scraper with caching and better error handling."""
    
    def __init__(self, base_url: str = None):
        self.base_url = base_url or SCRAPING.get("base_url", "https://bhfdsc.github.io/documentation/")
        self.scraped_content: Dict[str, str] = {}
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': SCRAPING.get("user_agent", 'Mozilla/5.0 (compatible; BHF-DSC-QA-Bot/1.0)')
        })
        self.cache_file = os.path.join(tempfile.gettempdir(), CACHE.get("cache_file", "bhf_dsc_content_cache.json"))
    
    def load_cached_content(self) -> Optional[Dict[str, Dict[str, str]]]:
        """Load content from cache if available and not expired."""
        if not CACHE.get("enable_content_cache", True):
            return None
            
        try:
            if os.path.exists(self.cache_file):
                cache_age = time.time() - os.path.getmtime(self.cache_file)
                cache_expiry = CACHE.get("cache_expiry", 3600)
                
                if cache_age < cache_expiry:
                    with open(self.cache_file, 'r', encoding='utf-8') as f:
                        cached_data = json.load(f)
                    logger.info(f"Loaded cached content from {self.cache_file}")
                    return cached_data
                else:
                    logger.info("Cache expired, will fetch fresh content")
        except Exception as e:
            logger.warning(f"Failed to load cache: {e}")
        
        return None
    
    def save_content_to_cache(self, content: Dict[str, Dict[str, str]]):
        """Save content to cache."""
        if not CACHE.get("enable_content_cache", True):
            return
            
        try:
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(content, f, indent=2, ensure_ascii=False)
            logger.info(f"Saved content to cache: {self.cache_file}")
        except Exception as e:
            logger.error(f"Failed to save cache: {e}")
    
    def clean_text(self, text: str) -> str:
        """Clean and normalize text content using configuration."""
        cleaning_patterns = PROCESSING.get("cleaning_patterns", [
            r'\[.*?\]\(\)',
            r'!\[\]\(\)',
            r'\s+',
        ])
        
        for pattern in cleaning_patterns[:-1]:  # All but whitespace pattern
            text = re.sub(pattern, '', text)
        
        # Apply whitespace normalization last
        text = re.sub(cleaning_patterns[-1], ' ', text)
        
        return text.strip()
    
    def extract_content_from_soup(self, soup: BeautifulSoup) -> str:
        """Extract main content from BeautifulSoup object."""
        # Remove unwanted elements
        remove_elements = PROCESSING.get("remove_elements", ["script", "style"])
        for element_type in remove_elements:
            for element in soup(element_type):
                element.decompose()
        
        # Try content selectors in order of preference
        content_selectors = PROCESSING.get("content_selectors", ["main", "article"])
        content_text = ""
        
        for selector in content_selectors:
            content = soup.select_one(selector)
            if content:
                content_text = content.get_text()
                break
        
        # Fallback to body if no main content found
        if not content_text:
            body = soup.find('body')
            content_text = body.get_text() if body else soup.get_text()
        
        return self.clean_text(content_text)
    
    def scrape_page(self, url: str) -> Dict[str, str]:
        """Scrape content from a single page with enhanced error handling."""
        try:
            timeout = SCRAPING.get("timeout", 10)
            response = self.session.get(url, timeout=timeout)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Extract title
            title = soup.find('title')
            title_text = title.get_text().strip() if title else "Untitled"
            
            # Extract content
            content_text = self.extract_content_from_soup(soup)
            
            # Apply content length limits
            max_length = SCRAPING.get("max_content_length", 10000)
            if len(content_text) > max_length:
                content_text = content_text[:max_length] + "... [content truncated]"
            
            return {
                'title': title_text,
                'content': content_text,
                'url': url,
                'scraped_at': datetime.now().isoformat()
            }
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Request error for {url}: {str(e)}")
            return {
                'title': "Request Error",
                'content': f"Failed to fetch content from {url}: {str(e)}",
                'url': url,
                'scraped_at': datetime.now().isoformat(),
                'error': True
            }
        except Exception as e:
            logger.error(f"Unexpected error scraping {url}: {str(e)}")
            return {
                'title': "Scraping Error", 
                'content': f"Unexpected error processing {url}: {str(e)}",
                'url': url,
                'scraped_at': datetime.now().isoformat(),
                'error': True
            }
    
    def discover_pages(self) -> List[str]:
        """Discover available pages with configurable paths."""
        pages = [self.base_url]
        
        additional_paths = SCRAPING.get("additional_paths", [])
        for path in additional_paths:
            full_url = urljoin(self.base_url, path)
            pages.append(full_url)
        
        return list(set(pages))  # Remove duplicates
    
    def scrape_all_content(self, use_cache: bool = True) -> Dict[str, Dict[str, str]]:
        """Scrape content from all discoverable pages."""
        # Try to load from cache first
        if use_cache:
            cached_content = self.load_cached_content()
            if cached_content:
                return cached_content
        
        pages = self.discover_pages()
        all_content = {}
        delay = SCRAPING.get("delay_between_requests", 0.5)
        min_content_length = SCRAPING.get("min_content_length", 100)
        
        logger.info(f"Scraping {len(pages)} pages...")
        
        for i, url in enumerate(pages):
            try:
                logger.info(f"Scraping ({i+1}/{len(pages)}): {url}")
                content = self.scrape_page(url)
                
                # Only keep substantial content without errors
                if (not content.get('error', False) and 
                    content['content'] and 
                    len(content['content']) > min_content_length):
                    all_content[url] = content
                
                # Be respectful with requests
                if i < len(pages) - 1:
                    time.sleep(delay)
                    
            except Exception as e:
                logger.error(f"Failed to process {url}: {str(e)}")
                continue
        
        self.scraped_content = all_content
        
        # Save to cache
        if use_cache and all_content:
            self.save_content_to_cache(all_content)
        
        logger.info(f"Successfully scraped {len(all_content)} pages")
        return all_content

class EnhancedBHFDocumentationQA:
    """Enhanced Q&A system with improved search and response generation."""
    
    def __init__(self, api_key: str):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.content_database: Dict[str, Dict[str, str]] = {}
    
    def load_content(self, content: Dict[str, Dict[str, str]]):
        """Load scraped content into the Q&A system."""
        self.content_database = content
        logger.info(f"Loaded {len(content)} pages into Q&A system")
    
    def calculate_relevance_score(self, query: str, content: Dict[str, str]) -> float:
        """Calculate relevance score for content based on query."""
        query_lower = query.lower()
        content_lower = content['content'].lower()
        title_lower = content['title'].lower()
        
        query_words = [word for word in query_lower.split() 
                      if len(word) >= SEARCH.get("min_word_length", 3)]
        
        if not query_words:
            return 0
        
        score = 0
        title_weight = SEARCH.get("title_weight", 3)
        content_weight = SEARCH.get("content_weight", 1)
        
        for word in query_words:
            # Title matches are weighted higher
            title_matches = title_lower.count(word)
            content_matches = content_lower.count(word)
            
            score += title_matches * title_weight
            score += content_matches * content_weight
        
        # Normalize by query length
        normalized_score = score / len(query_words)
        
        return normalized_score
    
    def search_relevant_content(self, query: str) -> str:
        """Search for relevant content with improved scoring."""
        if not self.content_database:
            return ""
        
        scored_content = []
        
        for url, content in self.content_database.items():
            score = self.calculate_relevance_score(query, content)
            if score > 0:
                scored_content.append((score, url, content))
        
        # Sort by relevance score
        scored_content.sort(key=lambda x: x[0], reverse=True)
        
        # Take top results
        max_results = SEARCH.get("max_results", 3)
        top_content = scored_content[:max_results]
        
        if not top_content:
            return ""
        
        # Compile context
        context_parts = []
        max_source_length = ANTHROPIC.get("max_source_length", 2000)
        
        for score, url, content in top_content:
            context_part = f"\n--- Source: {content['title']} ---"
            context_part += f"\nURL: {url}"
            context_part += f"\nRelevance Score: {score:.2f}"
            
            # Truncate content if too long
            content_text = content['content']
            if len(content_text) > max_source_length:
                content_text = content_text[:max_source_length] + "... [content truncated]"
            
            context_part += f"\nContent:\n{content_text}\n"
            context_parts.append(context_part)
        
        return "\n".join(context_parts)
    
    def generate_response(self, question: str, context: str) -> str:
        """Generate response using Anthropic API with enhanced prompting."""
        system_prompt = f"""You are a helpful assistant specializing in the BHF Data Science Centre documentation and research programmes. Your role is to help users understand:

- CVD-COVID-UK and COVID-IMPACT research programmes
- Available datasets in NHS England SDE, SAIL Databank, and National Safe Haven
- Data access procedures and approval processes
- Research tools and resources
- Team information and contacts

Key guidelines:
1. Use only the provided documentation content to answer questions
2. If information is incomplete, clearly state this and suggest contacting {CONTACT.get("team_email", "bhfdsc_hds@hdruk.ac.uk")}
3. Provide specific, actionable information when possible
4. Reference the source documentation when helpful
5. Be concise but comprehensive

Always maintain a professional, helpful tone while being accurate about what information is and isn't available in the documentation."""

        user_prompt = f"""Based on the BHF Data Science Centre documentation content below, please answer the user's question.

Documentation Content:
{context}

User Question: {question}

Please provide a helpful, accurate answer based on the documentation. If the documentation doesn't contain sufficient information, clearly state this and suggest next steps."""

        try:
            message = self.client.messages.create(
                model=ANTHROPIC.get("model", "claude-sonnet-4-20250514"),
                max_tokens=ANTHROPIC.get("max_tokens", 1000),
                system=system_prompt,
                messages=[{
                    "role": "user",
                    "content": user_prompt
                }]
            )
            
            return message.content[0].text
            
        except anthropic.APIError as e:
            logger.error(f"Anthropic API error: {e}")
            return f"I encountered an API error while processing your question. Please try again or contact {CONTACT.get('team_email', 'support')} for assistance."
        except Exception as e:
            logger.error(f"Unexpected error in response generation: {e}")
            return f"An unexpected error occurred while processing your question. Please try again."
    
    def answer_question(self, question: str) -> str:
        """Answer a question using enhanced search and response generation."""
        if not question.strip():
            return "Please provide a question about the BHF Data Science Centre documentation."
        
        # Search for relevant content
        context = self.search_relevant_content(question)
        
        if not context.strip():
            return f"""I couldn't find relevant information in the BHF Data Science Centre documentation to answer your question. 

This system can help with questions about:
- CVD-COVID-UK and COVID-IMPACT research programmes
- Available datasets and data access procedures
- Research tools and resources
- Team information and contacts

For specific questions about research or data access, please contact the team directly at {CONTACT.get("team_email", "bhfdsc_hds@hdruk.ac.uk")}."""
        
        # Generate response
        return self.generate_response(question, context)

def display_content_statistics(content: Dict[str, Dict[str, str]]):
    """Display statistics about loaded content."""
    if not content:
        return
    
    total_pages = len(content)
    total_chars = sum(len(page['content']) for page in content.values())
    avg_length = total_chars // total_pages if total_pages > 0 else 0
    
    # Find most recent scraping time
    scrape_times = [page.get('scraped_at', '') for page in content.values()]
    most_recent = max(scrape_times) if scrape_times else 'Unknown'
    
    st.markdown(f"""
    <div class="content-stats">
        <h4>📊 Content Statistics</h4>
        <ul>
            <li><strong>Pages loaded:</strong> {total_pages}</li>
            <li><strong>Total content:</strong> {total_chars:,} characters</li>
            <li><strong>Average page length:</strong> {avg_length:,} characters</li>
            <li><strong>Last updated:</strong> {most_recent[:19] if most_recent != 'Unknown' else 'Unknown'}</li>
        </ul>
    </div>
    """, unsafe_allow_html=True)

def display_example_questions():
    """Display example questions users can ask."""
    example_questions = UI.get("example_questions", [
        "How do I access data through the CVD-COVID-UK programme?",
        "What datasets are available?",
        "Who are the team members?",
    ])
    
    st.markdown("""
    <div class="question-suggestions">
        <h4>💭 Try asking questions like:</h4>
    </div>
    """, unsafe_allow_html=True)
    
    # Display questions in columns
    cols = st.columns(2)
    for i, question in enumerate(example_questions):
        with cols[i % 2]:
            if st.button(f"❓ {question}", key=f"example_{i}"):
                st.session_state['example_question'] = question

def main():
    """Enhanced main Streamlit application."""
    
    # Header
    st.markdown(f"""
    <div class="main-header">
        <h1>{UI.get('page_icon', '🫀')} {UI.get('page_title', 'BHF Data Science Centre Documentation Q&A')}</h1>
        <p>Ask questions about BHF DSC documentation, research programmes, datasets, and tools.</p>
    </div>
    """, unsafe_allow_html=True)
    
    # Sidebar
    with st.sidebar:
        st.markdown('<div class="sidebar-content">', unsafe_allow_html=True)
        st.header("🔧 Configuration")
        
        # API Key
        api_key = st.text_input(
            "Anthropic API Key",
            type="password",
            help="Enter your Anthropic API key for AI-powered responses",
            placeholder="sk-ant-..."
        )
        
        # Content management
        st.markdown("---")
        st.subheader("📚 Content Management")
        
        col1, col2 = st.columns(2)
        with col1:
            refresh_btn = st.button("🔄 Refresh", help="Fetch latest content from documentation")
        with col2:
            clear_cache_btn = st.button("🗑️ Clear Cache", help="Clear cached content")
        
        if clear_cache_btn:
            cache_file = os.path.join(tempfile.gettempdir(), CACHE.get("cache_file", "bhf_dsc_content_cache.json"))
            try:
                if os.path.exists(cache_file):
                    os.remove(cache_file)
                    st.success("Cache cleared!")
                else:
                    st.info("No cache to clear")
            except Exception as e:
                st.error(f"Error clearing cache: {e}")
        
        st.markdown("---")
        st.subheader("ℹ️ About")
        st.markdown(f"""
        This system searches through the [BHF Data Science Centre documentation]({SCRAPING.get('base_url')}) 
        to answer questions about:
        
        - 🔬 CVD-COVID-UK/COVID-IMPACT programmes
        - 📊 Available datasets and coverage  
        - 🛠️ Research tools and resources
        - 📋 Data access procedures
        - 👥 Team information
        - 📞 Contact details
        """)
        
        st.markdown("---")
        st.info(f"💌 **Need help?**\nContact: {CONTACT.get('team_email', 'bhfdsc_hds@hdruk.ac.uk')}")
        st.markdown('</div>', unsafe_allow_html=True)
    
    # Initialize session state
    for key, default in [
        ('documentation_content', {}),
        ('conversation_history', []),
        ('example_question', None)
    ]:
        if key not in st.session_state:
            st.session_state[key] = default
    
    # Check API key
    if not api_key:
        st.markdown("""
        <div class="status-warning">
            ⚠️ <strong>API Key Required</strong><br>
            Please enter your Anthropic API key in the sidebar to start using the Q&A system.
        </div>
        """, unsafe_allow_html=True)
        display_example_questions()
        st.stop()
    
    # Initialize systems
    qa_system = EnhancedBHFDocumentationQA(api_key)
    
    # Content loading
    if refresh_btn or not st.session_state['documentation_content']:
        with st.spinner("🔍 Fetching BHF DSC documentation content..."):
            try:
                scraper = EnhancedBHFDocumentationScraper()
                content = scraper.scrape_all_content(use_cache=not refresh_btn)
                st.session_state['documentation_content'] = content
                
                if content:
                    st.markdown(f"""
                    <div class="status-success">
                        ✅ <strong>Content Loaded</strong><br>
                        Successfully loaded documentation from {len(content)} pages.
                    </div>
                    """, unsafe_allow_html=True)
                else:
                    st.markdown("""
                    <div class="status-warning">
                        ⚠️ <strong>No Content</strong><br>
                        No content was loaded. Please check the documentation website.
                    </div>
                    """, unsafe_allow_html=True)
                    
            except Exception as e:
                st.markdown(f"""
                <div class="status-error">
                    ❌ <strong>Loading Error</strong><br>
                    Failed to load content: {str(e)}
                </div>
                """, unsafe_allow_html=True)
                logger.error(f"Content loading error: {e}")
    
    # Load content into Q&A system
    qa_system.load_content(st.session_state['documentation_content'])
    
    # Display content statistics
    if st.session_state['documentation_content']:
        display_content_statistics(st.session_state['documentation_content'])
    
    # Example questions
    display_example_questions()
    
    # Question input
    st.markdown("---")
    st.header("❓ Ask Your Question")
    
    # Use example question if selected
    default_question = ""
    if st.session_state['example_question']:
        default_question = st.session_state['example_question']
        st.session_state['example_question'] = None  # Clear after use
    
    question = st.text_area(
        "What would you like to know?",
        value=default_question,
        placeholder="e.g., How do I access CVD-COVID-UK data? What datasets are available in the NHS England SDE?",
        height=100
    )
    
    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        ask_btn = st.button("🔍 Ask Question", type="primary", disabled=not question.strip())
    with col2:
        clear_history_btn = st.button("🗑️ Clear History")
    
    if clear_history_btn:
        st.session_state['conversation_history'] = []
        st.rerun()
    
    # Process question
    if ask_btn and question.strip():
        if not st.session_state['documentation_content']:
            st.error("Please wait for content to load before asking questions.")
        else:
            with st.spinner("🤔 Searching documentation and generating answer..."):
                try:
                    answer = qa_system.answer_question(question)
                    
                    # Add to conversation history
                    st.session_state['conversation_history'].append({
                        'question': question.strip(),
                        'answer': answer,
                        'timestamp': time.time()
                    })
                    
                    # Limit conversation history
                    max_history = UI.get('max_conversation_history', 50)
                    if len(st.session_state['conversation_history']) > max_history:
                        st.session_state['conversation_history'] = st.session_state['conversation_history'][-max_history:]
                    
                except Exception as e:
                    st.error(f"Error processing question: {str(e)}")
                    logger.error(f"Question processing error: {e}")
    
    # Display conversation history
    if st.session_state['conversation_history']:
        st.markdown("---")
        st.header("💬 Conversation History")
        
        for i, conv in enumerate(reversed(st.session_state['conversation_history'])):
            with st.expander(
                f"❓ {conv['question'][:80]}{'...' if len(conv['question']) > 80 else ''}",
                expanded=(i == 0)
            ):
                timestamp = datetime.fromtimestamp(conv['timestamp']).strftime("%Y-%m-%d %H:%M:%S")
                
                st.markdown(f"""
                <div class="chat-message user-message">
                    <strong>🙋 Your Question ({timestamp}):</strong><br>
                    {conv['question']}
                </div>
                """, unsafe_allow_html=True)
                
                st.markdown(f"""
                <div class="chat-message assistant-message">
                    <strong>🫀 BHF DSC Assistant:</strong><br>
                    {conv['answer']}
                </div>
                """, unsafe_allow_html=True)
    
    # Footer
    st.markdown("---")
    st.markdown(f"""
    <div style="text-align: center; color: #666; padding: 1rem;">
        <p><strong>BHF Data Science Centre Documentation Q&A System</strong></p>
        <p>
            <a href="{SCRAPING.get('base_url', '#')}" target="_blank">📚 Visit Documentation</a> | 
            <a href="mailto:{CONTACT.get('team_email', '#')}">📧 Contact Team</a> | 
            Powered by Claude AI
        </p>
    </div>
    """, unsafe_allow_html=True)

if __name__ == "__main__":
    main()

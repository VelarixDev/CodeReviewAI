import os
import shutil
import uuid
import logging
import re
from typing import List, Optional
from git import Repo, GitCommandError
try:
    from langchain_text_splitters import RecursiveCharacterTextSplitter, Language
    from langchain_huggingface import HuggingFaceEmbeddings
    from langchain_chroma import Chroma
except ImportError as e:
    raise ImportError(f"Required libraries are not installed. Install them with the command:\n'pip install -U langchain-text-splitters langchain-huggingface chromadb'") from e

# Logging configuration
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

def validate_url(repo_url: str) -> bool:
    """Validates repository URL (only HTTP/HTTPS)."""
    pattern = re.compile(r'^https?://[a-zA-Z0-9.-]+(/[\w\d./-]*)?$')
    return pattern.match(repo_url) is not None

def safe_remove_directory(path: str):
    """Safely removes a directory, handling permission errors."""
    if os.path.exists(path):
        try:
            shutil.rmtree(path)
            logger.info(f"Temporary directory deleted: {path}")
        except Exception as e:
            logger.error(f"Could not remove directory {path}: {e}. Continuing.")

def clone_repository(repo_url: str, target_dir: Optional[str] = None) -> str:
    """Clones a repository into a secure temporary directory."""
    if not validate_url(repo_url):
        raise ValueError("Invalid URL. Use only http:// or https://")

    # Create a unique temporary directory to avoid conflicts and Path Traversal
    temp_dir = os.path.join(os.getcwd(), f"repo_{uuid.uuid4().hex[:8]}")
    try:
        logger.info(f"Cloning repository {repo_url} into {temp_dir}...")
        Repo.clone_from(repo_url, temp_dir)
        return temp_dir
    except GitCommandError as e:
        raise RuntimeError(f"Repository cloning error: {e}") from e

def extract_python_code(base_path: str):
    """Extracts code from .py files, preventing Path Traversal."""
    splitter = RecursiveCharacterTextSplitter.from_language(Language.PYTHON, chunk_size=300, chunk_overlap=50)
    all_chunks = []

    for root, _, files in os.walk(base_path):
        # Check: ensure we don't escape base_path (protection against symlinks outside the repo)
        if not os.path.abspath(root).startswith(os.path.abspath(base_path)):
            continue

        for file in files:
            if file.endswith('.py'):
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        code_text = f.read()
                        chunks = splitter.create_documents([code_text])
                        all_chunks.extend(chunks)
                except Exception as e:
                    logger.warning(f"Could not read file {file}: {e}")

    return all_chunks, len(files)

def index_to_chroma(docs):
    """Indexes documents in ChromaDB."""
    if not docs:
        raise ValueError("No documents to index")

    logger.info("Initializing embeddings (this may take a moment)...")
    embeddings = HuggingFaceEmbeddings(model_name='all-MiniLM-L6-v2')
    db = Chroma.from_documents(
        documents=docs, 
        embedding=embeddings, 
        persist_directory="./chroma_db",
        collection_name="my_codebase"
    )
    logger.info("Data successfully saved to ChromaDB (./chroma_db)")
    return db

def analyze_repo(repo_url: str):
    """Main repository analysis function."""
    temp_dir = None
    try:
        # 1. Clone with URL validation and secure path
        temp_dir = clone_repository(repo_url)

        # 2. Extract code (with Path Traversal protection)
        all_chunks, py_files_count = extract_python_code(temp_dir)

        if all_chunks:
            logger.info(f"Python files found: {py_files_count}. Chunks created: {len(all_chunks)}")
            
            # 3. Index in ChromaDB
            db = index_to_chroma(all_chunks)

            # Test search (optional, can be removed for production)
            query = "Where does currency conversion happen?"
            results = db.similarity_search(query, k=1)
            if results:
                print("\n🔍 Sample search result:")
                print("-------------------")
                print(results[0].page_content[:500] + ("..." if len(results[0].page_content) > 500 else ""))
                print("-------------------\n")

        else:
            logger.warning("No Python files found in the repository.")

    except Exception as e:
        logger.error(f"Error processing repository {repo_url}: {e}")
    finally:
        # 4. Resource cleanup (guaranteed temporary directory removal)
        if temp_dir and os.path.exists(temp_dir):
            safe_remove_directory(temp_dir)

def main():
    """Entry point."""
    REPO_URL = "https://github.com/VelarixDev/conveter-TgBot"  # Replace with the desired URL
    analyze_repo(REPO_URL)

def search_code(query: str, k: int = 3) -> str:
    try:
        from langchain_huggingface import HuggingFaceEmbeddings
        from langchain_chroma import Chroma
        
        logger.info(f"Searching for query: {query}")
        embeddings = HuggingFaceEmbeddings(model_name='all-MiniLM-L6-v2')
        
        # IMPORTANT: the argument is named embedding_function here!
        db = Chroma(
            persist_directory="./chroma_db", 
            embedding_function=embeddings,
            collection_name="my_codebase"
        )
        
        results = db.similarity_search(query, k=k)
        if not results:
            return "No matches found."
            
        context = "\n\n---CHUNK---\n\n".join([doc.page_content for doc in results])
        return context
    except Exception as e:
        logger.error(f"Error searching ChromaDB: {e}")
        return "Code database not found"

if __name__ == "__main__":
    main()
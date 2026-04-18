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
    raise ImportError(f"Необходимые библиотеки не установлены. Установите их командой:\n'pip install -U langchain-text-splitters langchain-huggingface chromadb'") from e

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

def validate_url(repo_url: str) -> bool:
    """Проверяет валидность URL репозитория (только HTTP/HTTPS)."""
    pattern = re.compile(r'^https?://[a-zA-Z0-9.-]+(/[\w\d./-]*)?$')
    return pattern.match(repo_url) is not None

def safe_remove_directory(path: str):
    """Безопасно удаляет директорию, обрабатывая ошибки доступа."""
    if os.path.exists(path):
        try:
            shutil.rmtree(path)
            logger.info(f"Удалена временная папка: {path}")
        except Exception as e:
            logger.error(f"Не удалось удалить директорию {path}: {e}. Продолжаем работу.")

def clone_repository(repo_url: str, target_dir: Optional[str] = None) -> str:
    """Клонирует репозиторий в безопасную временную папку."""
    if not validate_url(repo_url):
        raise ValueError("Некорректный URL-адрес. Используйте только http:// или https://")

    # Создаем уникальную временную директорию, чтобы избежать конфликтов и Path Traversal
    temp_dir = os.path.join(os.getcwd(), f"repo_{uuid.uuid4().hex[:8]}")
    try:
        logger.info(f"Клонирование репозитория {repo_url} в {temp_dir}...")
        Repo.clone_from(repo_url, temp_dir)
        return temp_dir
    except GitCommandError as e:
        raise RuntimeError(f"Ошибка клонирования репозитория: {e}") from e

def extract_python_code(base_path: str):
    """Извлекает код из .py файлов, предотвращая Path Traversal."""
    splitter = RecursiveCharacterTextSplitter.from_language(Language.PYTHON, chunk_size=300, chunk_overlap=50)
    all_chunks = []

    for root, _, files in os.walk(base_path):
        # Проверка: не выходим ли мы за пределы base_path (защита от символических ссылок вне репозитория)
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
                    logger.warning(f"Не удалось прочитать файл {file}: {e}")

    return all_chunks, len(files)

def index_to_chroma(docs):
    """Индексирует документы в ChromaDB."""
    if not docs:
        raise ValueError("Нет документов для индексации")

    logger.info("Инициализация эмбеддингов (может занять время)...")
    embeddings = HuggingFaceEmbeddings(model_name='all-MiniLM-L6-v2')
    db = Chroma.from_documents(
        documents=docs, 
        embedding=embeddings, 
        persist_directory="./chroma_db",
        collection_name="my_codebase"
    )
    logger.info("Данные успешно сохранены в ChromaDB (./chroma_db)")
    return db

def analyze_repo(repo_url: str):
    """Основная функция анализа репозитория."""
    temp_dir = None
    try:
        # 1. Клонирование с валидацией URL и безопасным путем
        temp_dir = clone_repository(repo_url)

        # 2. Извлечение кода (с защитой от Path Traversal)
        all_chunks, py_files_count = extract_python_code(temp_dir)

        if all_chunks:
            logger.info(f"Найдено .py файлов: {py_files_count}. Создано чанков: {len(all_chunks)}")
            
            # 3. Индексация в ChromaDB
            db = index_to_chroma(all_chunks)

            # Тестовый поиск (опционально, можно убрать для продакшена)
            query = "Где происходит конвертация валют?"
            results = db.similarity_search(query, k=1)
            if results:
                print("\n🔍 Пример результата поиска:")
                print("-------------------")
                print(results[0].page_content[:500] + ("..." if len(results[0].page_content) > 500 else ""))
                print("-------------------\n")

        else:
            logger.warning("Python-файлы не найдены в репозитории.")

    except Exception as e:
        logger.error(f"Ошибка при обработке репозитория {repo_url}: {e}")
    finally:
        # 4. Очистка ресурсов (гарантированное удаление временной папки)
        if temp_dir and os.path.exists(temp_dir):
            safe_remove_directory(temp_dir)

def main():
    """Точка входа."""
    REPO_URL = "https://github.com/VelarixDev/conveter-TgBot"  # Замените на нужный URL
    analyze_repo(REPO_URL)

def search_code(query: str, k: int = 3) -> str:
    try:
        from langchain_huggingface import HuggingFaceEmbeddings
        from langchain_chroma import Chroma
        
        logger.info(f"Выполняю поиск по запросу: {query}")
        embeddings = HuggingFaceEmbeddings(model_name='all-MiniLM-L6-v2')
        
        # ВАЖНО: здесь аргумент называется embedding_function!
        db = Chroma(
            persist_directory="./chroma_db", 
            embedding_function=embeddings,
            collection_name="my_codebase"
        )
        
        results = db.similarity_search(query, k=k)
        if not results:
            return "Совпадений не найдено."
            
        context = "\n\n---ЧАНК---\n\n".join([doc.page_content for doc in results])
        return context
    except Exception as e:
        logger.error(f"Ошибка при поиске в ChromaDB: {e}")
        return "База данных кода не найдена"

if __name__ == "__main__":
    main()
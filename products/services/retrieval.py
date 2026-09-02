import re
import logging
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from taxonomy.models import TaxonomyCategory

logger = logging.getLogger(__name__)

def stem_word(w):
    w = w.lower().strip()
    if len(w) > 3 and w.endswith('s') and not w.endswith('ss'):
        return w[:-1]
    return w

class TaxonomyRetrievalService:
    _instance = None

    def __init__(self):
        self.vectorizer = None
        self.tfidf_matrix = None
        self.category_list = []
        self._is_initialized = False

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def initialize(self, force=False):
        cat_count = TaxonomyCategory.objects.count()
        if self._is_initialized and not force and len(self.category_list) == cat_count and cat_count > 0:
            return

        categories = list(TaxonomyCategory.objects.all())
        if not categories:
            logger.warning("No Taxonomy Categories in database yet to initialize retrieval service.")
            return

        self.category_list = categories
        corpus = []
        for cat in categories:
            stemmed_name = ' '.join([stem_word(w) for w in cat.name.split()])
            stemmed_path = ' '.join([stem_word(w) for w in cat.full_path.split()])
            # Heavily weight leaf category name and level depth
            text = f"{cat.name} {cat.name} {stemmed_name} {stemmed_name} {stemmed_name} {cat.full_path} {stemmed_path}"
            corpus.append(text)

        self.vectorizer = TfidfVectorizer(
            stop_words='english',
            ngram_range=(1, 2),
            sublinear_tf=True
        )
        self.tfidf_matrix = self.vectorizer.fit_transform(corpus)
        self._is_initialized = True
        logger.info(f"Initialized TaxonomyRetrievalService with {len(categories)} categories.")

    def retrieve_candidates(self, product_dict, top_n=15):
        if not self._is_initialized:
            self.initialize()

        if not self._is_initialized or not self.category_list:
            return []

        title = product_dict.get('title', '')
        source_cat = product_dict.get('product_category', '')
        source_subcat = product_dict.get('product_subcategory', '')
        materials = product_dict.get('materials', '')

        # Construct query with heavy weight on Title
        raw_text = f"{title} {title} {source_cat} {source_subcat} {materials}"
        stemmed_tokens = [stem_word(w) for w in re.findall(r'\w+', raw_text)]
        query_text = f"{raw_text} {' '.join(stemmed_tokens)}"

        if not query_text.strip():
            return [{'category': c, 'retrieval_score': 0.5} for c in self.category_list[:top_n]]

        query_vec = self.vectorizer.transform([query_text])
        sims = cosine_similarity(query_vec, self.tfidf_matrix)[0]

        title_stems = set([stem_word(w) for w in re.findall(r'\w+', title) if len(w) > 2])
        subcat_stems = set([stem_word(w) for w in re.findall(r'\w+', source_subcat) if len(w) > 2])
        cat_stems = set([stem_word(w) for w in re.findall(r'\w+', source_cat) if len(w) > 2])

        candidate_scores = []
        for idx, cat in enumerate(self.category_list):
            raw_sim = float(sims[idx])
            full_path_lower = cat.full_path.lower()
            cat_name_stems = set([stem_word(w) for w in re.findall(r'\w+', cat.name) if len(w) > 2])

            # Domain filtering: prevent matching unrelated verticals (e.g. Apparel/Pets for Office/Furniture)
            if any(term in cat_stems or term in title_stems for term in ['furniture', 'living', 'room', 'dining', 'bedroom', 'office', 'chair', 'table', 'sofa', 'stool', 'bed', 'desk']):
                if not (full_path_lower.startswith('furniture') or full_path_lower.startswith('home & garden') or full_path_lower.startswith('office supplies')):
                    raw_sim *= 0.01

            # Exact Title Leaf Match Boost
            if cat_name_stems and cat_name_stems.issubset(title_stems):
                raw_sim += 0.60
            elif cat_name_stems and cat_name_stems.intersection(title_stems):
                raw_sim += 0.40
            elif cat_name_stems and cat_name_stems.intersection(subcat_stems):
                raw_sim += 0.25

            # Contradiction Penalty between title noun and candidate leaf noun
            # e.g., Title contains "armchair" but candidate is "sofas" (without armchair in title)
            if 'armchair' in title_stems and 'sofa' in cat_name_stems and 'armchair' not in cat_name_stems:
                raw_sim *= 0.2
            if 'pencil' in title_stems and 'decor' in cat_name_stems and 'pencil' not in full_path_lower:
                raw_sim *= 0.3

            # Specificity / Depth bonus (favor deeper categories when relevant)
            raw_sim += (cat.level * 0.03)

            if raw_sim > 0.01:
                candidate_scores.append((idx, raw_sim))

        candidate_scores.sort(key=lambda x: x[1], reverse=True)
        top_candidates = candidate_scores[:top_n]

        candidates = []
        for idx, score in top_candidates:
            candidates.append({
                'category': self.category_list[idx],
                'retrieval_score': min(1.0, score)
            })

        return candidates

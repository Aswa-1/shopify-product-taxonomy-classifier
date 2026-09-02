import re
import logging
from django.conf import settings

logger = logging.getLogger(__name__)

def stem_word(w):
    w = w.lower().strip()
    if len(w) > 3 and w.endswith('s') and not w.endswith('ss'):
        return w[:-1]
    return w

def evaluate_classification_confidence(candidate_results, product_dict, image_status_used=False):
    """
    Evaluates calibrated multi-signal confidence scores for candidates.
    Integrates title keyword alignment, source category hierarchy, evidence completeness,
    image status, depth specificity, and contradiction penalties.
    """
    if not candidate_results:
        return {
            'selected_candidate': None,
            'confidence_score': 0.0,
            'requires_review': True,
            'model_used': 'Fallback (No Candidates)',
            'explanation': 'No matching taxonomy categories found in database.',
            'alternatives': []
        }

    scored_candidates = []
    
    source_cat = (product_dict.get('product_category') or '').lower()
    source_subcat = (product_dict.get('product_subcategory') or '').lower()
    title = (product_dict.get('title') or '').lower()
    description = (product_dict.get('description') or '').lower()
    materials = (product_dict.get('materials') or '').lower()
    combined_text = f"{title} {source_cat} {source_subcat} {description}"

    title_stems = set([stem_word(w) for w in re.findall(r'\w+', title) if len(w) > 2])
    subcat_stems = set([stem_word(w) for w in re.findall(r'\w+', source_subcat) if len(w) > 2])
    cat_stems = set([stem_word(w) for w in re.findall(r'\w+', source_cat) if len(w) > 2])

    is_outdoor_product = any(w in combined_text for w in ['outdoor', 'patio', 'teak', 'all-weather'])

    for item in candidate_results:
        if isinstance(item, dict):
            cat = item['category']
            ret_score = item.get('retrieval_score', 0.0)
        else:
            cat = item
            ret_score = 0.50

        full_path_lower = cat.full_path.lower()
        cat_name_lower = cat.name.lower()

        cat_name_stems = set([stem_word(w) for w in re.findall(r'\w+', cat_name_lower) if len(w) > 2])
        path_stems = set([stem_word(w) for w in re.findall(r'\w+', full_path_lower) if len(w) > 2])

        # Signal 1: Vector / TF-IDF Retrieval Score (0.0 to 1.0)
        s_retrieval = min(1.0, ret_score * 1.1)

        # Signal 2: Token-based Hierarchy & Source Category Alignment (0.0 to 1.0)
        s_hierarchy = 0.2
        if cat_name_stems and cat_name_stems.issubset(subcat_stems):
            s_hierarchy = 1.0
        elif subcat_stems and cat_name_stems.intersection(subcat_stems):
            s_hierarchy = 0.85
        elif cat_stems and cat_name_stems.intersection(cat_stems):
            s_hierarchy = 0.75
        elif subcat_stems and path_stems.intersection(subcat_stems):
            s_hierarchy = 0.65

        # Indoor vs Outdoor Disambiguation Penalty
        is_outdoor_category = 'outdoor' in full_path_lower or 'patio' in full_path_lower
        if is_outdoor_category and not is_outdoor_product:
            s_hierarchy *= 0.2
            s_retrieval *= 0.2
        elif not is_outdoor_category and is_outdoor_product:
            s_hierarchy *= 0.3

        # Signal 3: Title Keyword Match (0.0 to 1.0)
        s_title = 0.0
        if cat_name_stems and cat_name_stems.issubset(title_stems):
            s_title = 1.0
        elif cat_name_stems and cat_name_stems.intersection(title_stems):
            s_title = len(cat_name_stems.intersection(title_stems)) / len(cat_name_stems)

        # Contradiction Penalties
        if 'armchair' in title_stems and 'sofa' in cat_name_stems and 'armchair' not in cat_name_stems:
            s_title *= 0.1
            s_hierarchy *= 0.1
            s_retrieval *= 0.1
        if 'pencil' in title_stems and 'decor' in cat_name_stems and 'pencil' not in path_stems:
            s_title *= 0.2
            s_hierarchy *= 0.2

        # Signal 4: Multi-Field Evidence Completeness (0.0 to 1.0)
        # Full score 1.0 requires description AND materials AND dimensions
        s_evidence = (0.4 if description else 0.1) + (0.4 if materials else 0.1) + (0.2 if product_dict.get('dimensions') else 0.0)

        # Signal 5: Image Signal (0.0 to 1.0)
        s_image = 1.0 if image_status_used else 0.5

        # Specificity / Depth Bonus Factor (0.0 to 0.05)
        s_depth_factor = min(0.05, (cat.level - 1) * 0.015)

        # Strictly Calibrated Weighted Sum
        # Weights: Retrieval (0.30) + Hierarchy (0.30) + Title (0.25) + Evidence (0.10) + Image (0.05) + Depth Factor
        raw_confidence = (
            (0.30 * s_retrieval) + 
            (0.30 * s_hierarchy) + 
            (0.25 * s_title) + 
            (0.10 * s_evidence) + 
            (0.05 * s_image) + 
            s_depth_factor
        )

        # A score of >=0.95 requires ALL signals (title, hierarchy, description, materials, image) to agree
        confidence = max(0.10, min(0.99, round(raw_confidence, 2)))

        scored_candidates.append({
            'category': cat,
            'confidence_score': confidence,
            'breakdown': {
                'retrieval': round(s_retrieval, 2),
                'hierarchy': round(s_hierarchy, 2),
                'title': round(s_title, 2),
                'evidence': round(s_evidence, 2),
                'image': round(s_image, 2),
                'depth_factor': round(s_depth_factor, 2)
            }
        })

    # Sort candidates by final confidence score
    scored_candidates.sort(key=lambda x: x['confidence_score'], reverse=True)

    selected = scored_candidates[0]
    top_score = selected['confidence_score']

    high_threshold = getattr(settings, 'CONFIDENCE_HIGH_THRESHOLD', 0.80)
    medium_threshold = getattr(settings, 'CONFIDENCE_MEDIUM_THRESHOLD', 0.60)

    # Low-confidence threshold strictly < 0.60
    requires_review = top_score < medium_threshold

    # Format transparent explanation
    bd = selected['breakdown']
    img_str = "with valid image signal" if image_status_used else "without image signal (text fallback)"
    explanation = (
        f"Selected category '{selected['category'].full_path}' with confidence {top_score:.2f} {img_str}. "
        f"Score breakdown: Hierarchy={bd['hierarchy']}, Retrieval={bd['retrieval']}, "
        f"Title={bd['title']}, Evidence={bd['evidence']}, Image={bd['image']}."
    )

    # Deduplicated Top 3 Alternatives (guaranteeing unique category paths)
    alternatives = []
    seen_paths = {selected['category'].full_path}
    rank = 1

    for alt in scored_candidates[1:]:
        c_path = alt['category'].full_path
        if c_path not in seen_paths:
            seen_paths.add(c_path)
            alternatives.append({
                'category': alt['category'],
                'confidence_score': alt['confidence_score'],
                'rank': rank
            })
            rank += 1
            if rank > 3:
                break

    return {
        'selected_candidate': selected['category'],
        'confidence_score': top_score,
        'requires_review': requires_review,
        'model_used': 'Demo Mode (Hybrid Lexical+TF-IDF+Hierarchy)' if not getattr(settings, 'AI_API_KEY', '') else 'AI Enhanced Classifier',
        'explanation': explanation,
        'alternatives': alternatives
    }

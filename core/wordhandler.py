import inflect


class WordHandler:
    """Class to handle word processing for word clouds."""
    def __init__(self):
        self.p = inflect.engine()

        # Words that shouldn't be changed
        self.exceptions = {
            'this', 'is', 'was', 'has', 'does', 'species', 'series',
            'news', 'analysis', 'physics', 'mathematics', 'economics',
            'linguistics', 'statistics', 'politics', 'ethics', 'done'
        }

        self.stopwords = {
            'a', 'an', 'and', 'are', 'as', 'at', 'be', 'by', 'for', 'from',
            'has', 'he', 'in', 'is', 'it', 'its', 'of', 'on', 'that', 'the',
            'to', 'was', 'were', 'will', 'with', 'the', 'this', 'but', 'they',
            'have', 'had', 'what', 'when', 'where', 'who', 'which', 'why', 'how',
            'all', 'any', 'both', 'each', 'few', 'more', 'most', 'other', 'some',
            'such', 'no', 'nor', 'not', 'only', 'own', 'same', 'so', 'than', 'too',
            'very', 'can', 'just', 'should', 'now', 'i', 'you', 'your', 'we', 'my',
            'me', 'her', 'his', 'their', 'our', 'us', 'am', 'been', 'being', 'do',
            'does', 'did', 'doing', 'would', 'could', 'might', 'must', 'shall',
            'into', 'if', 'then', 'else', 'out', 'about', 'over', 'again', 'once',
            'under', 'further', 'before', 'after', 'above', 'below', 'up', 'down',
            'in', 'out', 'on', 'off', 'while', 'through'
        }

    # Example usage:
    def is_stop_word(self, word):
        return word.lower() in self.stopwords

    # Or to remove stop words from text:
    def remove_stop_words(self, text):
        words = text.split()
        return ' '.join(word for word in words if word.lower() not in self.stopwords)



    def to_singular(self, word):
        """Convert a word to its singular form."""
        # Check exceptions
        if word.lower() in self.exceptions:
            return word

        # Try to get singular form
        singular = self.p.singular_noun(word)

        # If word is already singular, singular_noun returns False
        return word if not singular else singular

    def process_text(self, text):
        """Process a full text string."""
        if not text:
            return text

        words = text.split()
        processed_words = self.process_list(words)
        return ' '.join(processed_words)

    def process_list(self, words):
        """Process a list of words."""
        return [self.to_singular(word) for word in words if (not self.is_stop_word(word) and not word.isnumeric())]

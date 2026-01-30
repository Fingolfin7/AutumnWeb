/**
 * Wordcloud Chart Module
 * Word frequency visualization from session notes
 */

(function() {
    const utils = window.AutumnCharts.utils;

    // ========================================================================
    // Wordcloud
    // ========================================================================

    function wordcloud(data, ctx, canvasId) {
        // List of common filler words to exclude
        const stopWords = new Set([
            "the", "and", "is", "in", "at", "of", "a", "an", "to", "for", "with",
            "on", "by", "it", "this", "that", "from", "as", "be", "are", "was",
            "were", "has", "have", "had", "but", "or", "not", "which", "we", "you",
            "they", "he", "she", "it", "i", "me", "my", "mine", "your", "yours",
            "about", "if", "so", "then", "there", "here", "where", "when", "how",
            "can", "will", "would", "could", "should", "may", "might", "must",
            "just", "also", "some", "all", "any", "more", "most", "other", "into",
            "over", "such", "no", "than", "too", "very", "just", "only", "own",
            "same", "so", "than", "too", "very", "will", "now", "been", "being",
            "each", "few", "both", "these", "those", "what", "while", "who",
            "whom", "why", "did", "does", "doing", "done", "get", "got", "getting"
        ]);

        // Extract words from all session notes
        let notesText = data.map(item => item.note || "").join(" ");
        let canvasElement = $(canvasId)[0];

        // Remove Markdown formatting using regex
        const cleanText = notesText
            .replace(/(\*{1,2}|_{1,2}|~{1,2})/g, '') // Remove bold/italic/strikethrough
            .replace(/#{1,6}\s/g, '') // Remove headers
            .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1') // Remove links, keep text
            .replace(/`[^`]+`/g, '') // Remove inline code
            .replace(/```[\s\S]*?```/g, '') // Remove code blocks
            .replace(/\s+/g, ' ') // Normalize whitespace
            .trim();

        // Count word frequencies, filtering out stop words
        const wordCounts = {};
        cleanText.toLowerCase().replace(/\b[a-z]+\b/g, word => {
            if (!stopWords.has(word) && word.length > 2) {
                wordCounts[word] = (wordCounts[word] || 0) + 1;
            }
        });

        // Convert to array format for wordcloud2.js and limit top N words
        const wordArray = Object.entries(wordCounts)
            .sort((a, b) => b[1] - a[1])
            .slice(0, 100)
            .map(([text, weight]) => [text, weight]);

        if (wordArray.length === 0) {
            utils.clearChart(ctx);
            return;
        }

        console.log('wordArray:', wordArray);

        // Store dimensions from container
        const container = $('#canvas_container');
        let prev_width = container[0]?.clientWidth || window.innerWidth * 0.8;
        let prev_height = container[0]?.clientHeight || window.innerHeight * 0.6;

        // Destroy existing Chart.js chart if it exists
        utils.clearChart(ctx);

        // Resize the canvas element
        canvasElement.width = prev_width;
        canvasElement.height = prev_height;

        // Calculate dynamic sizing
        let dynamicSize = wordArray.length > 50 ? 8 : 16;
        let largestFrequency = wordArray[0][1];
        let dynamicWeightFactor = dynamicSize * 30 / largestFrequency;

        // Initialize the word cloud
        WordCloud(canvasElement, {
            list: wordArray,
            gridSize: Math.round(dynamicSize * canvasElement.width / 1024),
            weightFactor: dynamicWeightFactor,
            fontFamily: 'Inter, system-ui, sans-serif',
            color: function(word, weight) {
                // Color based on weight - more frequent = warmer color
                const maxWeight = wordArray[0][1];
                const ratio = weight / maxWeight;
                const hue = 200 - (ratio * 160); // Blue to orange/red
                return `hsl(${hue}, 80%, 55%)`;
            },
            rotateRatio: 0.4,
            rotationSteps: 2,
            backgroundColor: 'transparent',
            drawOutOfBound: false,
            shrinkToFit: true,
            click: function(item) {
                // Optional: log clicked word
                console.log('Clicked:', item[0], 'Count:', item[1]);
            }
        });
    }

    // ========================================================================
    // Register chart
    // ========================================================================

    window.AutumnCharts.registerAll({
        wordcloud: wordcloud
    });

})();

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
        let canvasElement = $(canvasId)[0];
        const wordArray = data.map(item => [item.text, Number(item.weight)]);

        if (wordArray.length === 0) {
            utils.clearChart(ctx);
            return;
        }

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
        const dynamicSize = wordArray.length > 50 ? 8 : 16;
        const largestFrequency = wordArray[0][1];
        const smallestFrequency = wordArray[wordArray.length - 1][1];
        const frequencyRange = largestFrequency - smallestFrequency;
        const maxFontSize = Math.min(72, Math.max(36, canvasElement.width / 10));
        const minFontSize = Math.max(12, maxFontSize / 4);

        // Normalize frequencies into bounded font sizes. Multiplying raw counts
        // made uniformly frequent words hundreds of pixels tall, so WordCloud
        // could fail to place any of them and leave a blank canvas.
        const dynamicWeightFactor = function(weight) {
            if (!frequencyRange) return maxFontSize;
            const ratio = (weight - smallestFrequency) / frequencyRange;
            return minFontSize + ratio * (maxFontSize - minFontSize);
        };

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

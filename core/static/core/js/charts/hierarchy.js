/**
 * Hierarchy Charts Module
 * Treemap and Sunburst charts for hierarchical data visualization
 */

(function() {
    const utils = window.AutumnCharts.utils;

    // ========================================================================
    // Treemap Chart
    // ========================================================================

    function treemap_chart(data, ctx) {
        // Data comes in hierarchical format:
        // { name: "All", children: [{ name: "Context", children: [{ name: "Project", total_time: X, children: [...] }] }] }

        // Flatten the hierarchy for chartjs-chart-treemap
        const flatData = [];
        const contextColors = {};
        let colorIndex = 0;

        function processNode(node, path = [], depth = 0, contextName = null) {
            if (node.children && node.children.length > 0) {
                // This is a branch node
                if (depth === 1) {
                    // This is a context - assign it a color
                    contextName = node.name;
                    if (!contextColors[contextName]) {
                        contextColors[contextName] = utils.generateRandomColor(colorIndex++, 10);
                    }
                }

                node.children.forEach(child => {
                    processNode(child, [...path, node.name], depth + 1, contextName);
                });
            } else if (node.total_time > 0) {
                // This is a leaf node with time
                flatData.push({
                    name: node.name,
                    path: path.join('/'),
                    value: node.total_time / 60, // Convert to hours
                    context: contextName,
                    depth: depth
                });
            }
        }

        if (data.children) {
            data.children.forEach(child => processNode(child, [], 0));
        }

        // If no hierarchical data, fall back to flat project data
        if (flatData.length === 0 && Array.isArray(data)) {
            data.forEach((item, index) => {
                if (item.total_time > 0) {
                    flatData.push({
                        name: item.name,
                        path: item.context_name || 'General',
                        value: item.total_time / 60,
                        context: item.context_name || 'General',
                        depth: 1
                    });
                    if (!contextColors[item.context_name || 'General']) {
                        contextColors[item.context_name || 'General'] = utils.generateRandomColor(index, data.length);
                    }
                }
            });
        }

        if (flatData.length === 0) {
            utils.clearChart(ctx);
            return;
        }

        utils.clearChart(ctx);

        new Chart(ctx, {
            type: 'treemap',
            data: {
                datasets: [{
                    tree: flatData,
                    key: 'value',
                    groups: ['context', 'name'],
                    spacing: 1,
                    borderWidth: 2,
                    borderColor: 'rgba(255,255,255,0.8)',
                    backgroundColor: function(ctx) {
                        if (ctx.type !== 'data') return 'transparent';
                        const item = ctx.raw;
                        const context = item._data?.context || item.g;
                        const baseColor = contextColors[context] || 'hsl(200, 70%, 60%)';
                        // Vary lightness by depth
                        const depth = item._data?.depth || 0;
                        return baseColor.replace('70%)', `${70 - depth * 10}%)`);
                    },
                    labels: {
                        display: true,
                        align: 'center',
                        position: 'middle',
                        formatter: function(ctx) {
                            if (ctx.type !== 'data') return '';
                            const item = ctx.raw;
                            const value = item.v || item.value || 0;
                            if (value < 0.5) return ''; // Don't show labels for tiny boxes
                            const name = item.g || item._data?.name || '';
                            return `${name}\n${value.toFixed(1)}h`;
                        },
                        color: 'white',
                        font: {
                            size: 11,
                            weight: 'bold'
                        }
                    }
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    title: {
                        display: true,
                        text: 'Time Distribution (Treemap)'
                    },
                    legend: {
                        display: false
                    },
                    tooltip: {
                        callbacks: {
                            title: function(items) {
                                if (!items.length) return '';
                                const item = items[0].raw;
                                return item._data?.path || item.g || '';
                            },
                            label: function(ctx) {
                                const item = ctx.raw;
                                const value = item.v || item.value || 0;
                                const name = item.g || item._data?.name || '';
                                return `${name}: ${value.toFixed(2)} hours`;
                            }
                        }
                    }
                }
            }
        });
    }

    // ========================================================================
    // Sunburst Chart (using D3 for calculations, Chart.js doughnut for rendering)
    // ========================================================================

    function sunburst_chart(data, ctx) {
        // For sunburst, we'll create nested doughnut charts
        // Each ring represents a level: All -> Context -> Project -> SubProject

        // Build rings from hierarchical data
        const rings = [[], [], []]; // [contexts, projects, subprojects]
        const ringColors = [[], [], []];

        let contextIndex = 0;

        function processHierarchy(node, depth = 0, parentColor = null) {
            if (depth > 2) return; // Max 3 levels

            if (node.children && node.children.length > 0) {
                node.children.forEach((child, i) => {
                    let color;
                    if (depth === 0) {
                        // Context level
                        color = utils.generateRandomColor(contextIndex++, 10);
                    } else {
                        // Derive from parent color with variation
                        const hueMatch = parentColor?.match(/hsl\((\d+)/);
                        const baseHue = hueMatch ? parseInt(hueMatch[1]) : 0;
                        const variation = (i * 20) - 30;
                        color = `hsl(${(baseHue + variation + 360) % 360}, 70%, ${65 + depth * 5}%)`;
                    }

                    const totalTime = calculateTotalTime(child);
                    if (totalTime > 0) {
                        rings[depth].push({
                            name: child.name,
                            value: totalTime / 60,
                            parent: node.name
                        });
                        ringColors[depth].push(color);
                    }

                    processHierarchy(child, depth + 1, color);
                });
            }
        }

        function calculateTotalTime(node) {
            if (node.total_time) return node.total_time;
            if (node.children) {
                return node.children.reduce((sum, child) => sum + calculateTotalTime(child), 0);
            }
            return 0;
        }

        if (data.children) {
            processHierarchy(data);
        }

        // Fallback for flat data
        if (rings[0].length === 0 && Array.isArray(data)) {
            data.forEach((item, index) => {
                if (item.total_time > 0) {
                    rings[0].push({
                        name: item.name,
                        value: item.total_time / 60
                    });
                    ringColors[0].push(utils.generateRandomColor(index, data.length));
                }
            });
        }

        utils.clearChart(ctx);

        // Create multi-ring doughnut (sunburst approximation)
        const datasets = [];

        // Build datasets from inside out
        rings.forEach((ring, depth) => {
            if (ring.length > 0) {
                datasets.push({
                    label: ['Contexts', 'Projects', 'SubProjects'][depth],
                    data: ring.map(r => r.value),
                    backgroundColor: ringColors[depth],
                    borderWidth: 2,
                    borderColor: 'white',
                    // Adjust radius for each ring
                    weight: 1
                });
            }
        });

        if (datasets.length === 0) return;

        // Collect all labels
        const allLabels = rings.flat().map(r => r.name);

        new Chart(ctx, {
            type: 'doughnut',
            data: {
                labels: rings[0].map(r => r.name), // Only show outermost labels
                datasets: datasets
            },
            options: {
                responsive: true,
                cutout: '20%',
                plugins: {
                    title: {
                        display: true,
                        text: 'Time Distribution (Sunburst)'
                    },
                    legend: {
                        position: 'right',
                        labels: {
                            generateLabels: function(chart) {
                                // Only show legend for first dataset (contexts)
                                const dataset = chart.data.datasets[0];
                                return rings[0].map((item, i) => ({
                                    text: item.name,
                                    fillStyle: dataset.backgroundColor[i],
                                    hidden: false,
                                    index: i
                                }));
                            }
                        }
                    },
                    tooltip: {
                        callbacks: {
                            label: function(ctx) {
                                const datasetIndex = ctx.datasetIndex;
                                const dataIndex = ctx.dataIndex;
                                const ring = rings[datasetIndex];
                                if (ring && ring[dataIndex]) {
                                    const item = ring[dataIndex];
                                    return `${item.name}: ${item.value.toFixed(2)} hours`;
                                }
                                return '';
                            }
                        }
                    }
                }
            }
        });
    }

    // ========================================================================
    // Register charts
    // ========================================================================

    window.AutumnCharts.registerAll({
        treemap: treemap_chart,
        sunburst: sunburst_chart
    });

})();

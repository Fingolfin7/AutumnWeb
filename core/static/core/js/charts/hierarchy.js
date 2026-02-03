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
    // Register charts
    // ========================================================================

    window.AutumnCharts.registerAll({
        treemap: treemap_chart
    });

})();

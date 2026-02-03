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

        // Flatten the hierarchy for chartjs-chart-treemap - using projects as top-level grouping
        const flatData = [];
        const projectColors = {};
        let colorIndex = 0;

        function processNode(node, depth = 0) {
            if (depth === 0 && node.children && node.children.length > 0) {
                // This is a context level - skip to projects
                node.children.forEach(child => {
                    processNode(child, 1);
                });
            } else if (depth === 1 && node.total_time > 0) {
                // This is a project
                const projectName = node.name;
                if (!projectColors[projectName]) {
                    projectColors[projectName] = utils.generateRandomColor(colorIndex++, 20);
                }

                if (node.children && node.children.length > 0) {
                    // Project has subprojects - add each subproject
                    node.children.forEach(child => {
                        if (child.total_time > 0) {
                            flatData.push({
                                name: child.name,
                                project: projectName,
                                value: child.total_time / 60
                            });
                        }
                    });
                } else {
                    // Project has no subprojects - add the project itself
                    flatData.push({
                        name: projectName,
                        project: projectName,
                        value: node.total_time / 60
                    });
                }
            }
        }

        if (data.children) {
            data.children.forEach(child => processNode(child, 0));
        }

        // If no hierarchical data, fall back to flat project data
        if (flatData.length === 0 && Array.isArray(data)) {
            data.forEach((item, index) => {
                if (item.total_time > 0) {
                    flatData.push({
                        name: item.name,
                        project: item.name,
                        value: item.total_time / 60
                    });
                    if (!projectColors[item.name]) {
                        projectColors[item.name] = utils.generateRandomColor(index, data.length);
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
                    groups: ['project', 'name'],
                    spacing: 1,
                    borderWidth: 2,
                    borderColor: 'rgba(255,255,255,0.8)',
                    backgroundColor: function(ctx) {
                        if (ctx.type !== 'data') return 'transparent';
                        const item = ctx.raw;
                        // For data items, use _data.project; for group boxes, use item.g
                        const project = item._data?.project || item.g;
                        if (!project) return 'transparent';
                        return projectColors[project] || 'hsl(200, 70%, 60%)';
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

                            // For group boxes (project level), item.g is the project name and _data is undefined
                            // For data items (subprojects), _data.name is the subproject name
                            if (item._data && item._data.name) {
                                // This is a data item (subproject or project without subprojects)
                                return `${item._data.name}\n${value.toFixed(1)}h`;
                            } else if (item.g) {
                                // This is a group box (project container)
                                return item.g;
                            }
                            return '';
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
                                // For group boxes use item.g, for data items use _data.project
                                return item._data?.project || item.g || '';
                            },
                            label: function(ctx) {
                                const item = ctx.raw;
                                const value = item.v || item.value || 0;
                                // For group boxes, item.g is the name; for data items, _data.name
                                const name = item._data?.name || item.g || '';
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

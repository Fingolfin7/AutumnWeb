$(document).ready(function(){
    let selectType = $('#chart_type');
    let draw       = $('#draw');

    // Loading overlay helpers
    const $loading = $('#chart-loading');
    const $empty = $('#chart-empty');
    const $canvasContainer = $('#canvas_container');

    function showLoading(message = 'Loading chart…') {
        if (!$loading.length) return;
        $loading.find('.loading-text').text(message);
        $loading.attr('aria-busy', 'true').show();
    }

    function hideLoading() {
        if (!$loading.length) return;
        $loading.attr('aria-busy', 'false').hide();
    }

    function showEmpty() {
        if ($empty.length) $empty.show();
        if ($canvasContainer.length) $canvasContainer.hide();
    }

    function hideEmpty() {
        if ($empty.length) $empty.hide();
        if ($canvasContainer.length) $canvasContainer.show();
    }

    function clearChart(ctx) {
        try {
            const existing = Chart.getChart(ctx);
            if (existing) existing.destroy();
        } catch (e) {
            // ignore
        }
    }

    // Persist chart type from server-rendered data attribute (querystring)
    const preselectedType = selectType.data('selected');
    if (preselectedType) {
        selectType.val(preselectedType);
    }

    // set the default start date to the start of this month (only if empty)
    let current_date = new Date();
    if (!$('#start_date').val()) {
        $('#start_date').val(new Date(current_date.getFullYear(), current_date.getMonth(), 1).toISOString().split('T')[0]);
    }
    if (!$('#end_date').val()) {
        $('#end_date').val(new Date().toISOString().split('T')[0]);
    }

    function render() {
        showLoading('Loading chart…');

        let type = selectType.val();
        let canvasCtx = $('#chart')[0].getContext('2d');

        let start_date = $('#start_date').val();
        let end_date = $('#end_date').val();

        start_date = start_date ? format_date(new Date(start_date)) : "";
        end_date = end_date ? format_date(new Date(end_date)) : "";

        // project name is optional
        let project_name = ($('#project-search').val() || '').trim();

        // Context: '' means "All Contexts" in the form choices, so don't send it.
        let context_id = String($('#context-filter').val() || '').trim();
        if (!context_id) context_id = '';

        // Tags: be robust across different template renderings.
        // We prefer inputs inside #tag-filter, but fall back to any checked input with name="tags".
        let $tagInputs = $('#tag-filter input[type="checkbox"]:checked');
        if (!$tagInputs.length) {
            $tagInputs = $('input[type="checkbox"][name="tags"]:checked');
        }
        const tag_ids = $tagInputs
            .map(function(){ return String($(this).val()); })
            .get()
            .filter(v => v && v !== 'on');

        get_project_data(type, start_date, end_date, project_name, context_id, tag_ids)
          .then(data => {
            // If the API returns nothing, clear the old chart and show empty state
            if (!data || !data.length) {
              clearChart(canvasCtx);
              showEmpty();
              return;
            }

            hideEmpty();

            if (project_name && type === 'scatter'){
                type = 'scatter_subprojects';
            }

            const chartFns = {
              pie: pie_chart,
              bar: bar_graph,
              scatter: scatter_graph,
              scatter_subprojects: scatter_subproject_graph,
              calendar: calendar_graph,
              wordcloud: wordcloud,
              heatmap: heatmap_graph
            };
            type !== 'wordcloud' ? chartFns[type](data, canvasCtx): chartFns[type](data, canvasCtx, "#chart");
          })
          .catch(err => {
              console.error(err);
              // On error, clear old chart and show empty state so it's obvious something changed
              try { clearChart(canvasCtx); } catch(e) {}
              showEmpty();
          })
          .finally(() => {
              requestAnimationFrame(() => hideLoading());
          });
    }

    // initial draw
    render();
    draw.on('click', render);
});

function get_project_data(type, start_date="", end_date="", project_name="", context_id = "", tag_ids = []){
    let url = "";

    const wantSubprojects =
      project_name &&
      (type === 'pie' || type === 'bar');

    if (wantSubprojects) {
        url = $('#subprojects_tally_link').val();
    }
    else if (['scatter','calendar','heatmap'].includes(type)) {
        url = $('#sessions_link').val();
    }
    else if (type==='wordcloud') {
        url = $('#raw_sessions_link').val();
    }
    else {
        url = $('#projects_link').val();
    }

    // Build query string safely (supports repeated tags=1&tags=2)
    const qs = new URLSearchParams();
    if (project_name) qs.set('project_name', project_name);
    if (start_date) qs.set('start_date', start_date);
    if (end_date) qs.set('end_date', end_date);
    if (context_id) qs.set('context', context_id);
    if (Array.isArray(tag_ids) && tag_ids.length) {
        tag_ids.forEach(t => qs.append('tags', t));
    }

    const query = qs.toString();
    if (query) url += '?' + query;

    console.log(url);

    return new Promise((resolve, reject) => {
        $.ajax({
            url: url,
            type: 'GET',
            dataType: 'json',
            success: function(data) {
                resolve(data);
            },
            error: function(error) {
                reject(error);
            }
        });
    });
}

function generateRandomColor(element_position, element_count) {
    let hue = (element_position * 360) / element_count;
    return `hsl(${hue}, 100%, 70%)`;
}

function fillDates(minDate, maxDate) {
    // Generate all dates between minDate and maxDate
    const dateList = [];
    for (let date = new Date(minDate); date <= maxDate; date.setDate(date.getDate() + 1)) {
        dateList.push(new Date(date));
    }
    return dateList;
}

function getChartUnit(endDate, startDate, defaultUnit = 'week') {
    const msPerDay = 24 * 60 * 60 * 1000;
    const daysDifference = Math.round((endDate - startDate) / msPerDay);
    const monthsDifference = (endDate.getFullYear() - startDate.getFullYear()) * 12 + endDate.getMonth() - startDate.getMonth();

    if (daysDifference <= 21) {
        return 'day';
    } else if (daysDifference <= 90) {
        return 'week';
    } else if (monthsDifference <= 18) {
        return 'month';
    } else {
        return 'year';
    }
}

function format_date(date){
    let month = date.getMonth() + 1;
    let day = date.getDate();
    let year = date.getFullYear();

    //format date
    return `${month}-${day}-${year}`;
}

// heatmap helper count how many times each weekday occurs in the [start, end] range
function countWeekdays(startDate, endDate) {
  const counts = Array(7).fill(0);
  const d = new Date(startDate);
  while (d <= endDate) {
    counts[d.getDay()] += 1;
    d.setDate(d.getDate() + 1);
  }
  return counts;
}

function pie_chart(data, ctx) {
    // Generate colors dynamically based on the number of data points
    const colors = data.map((element, index) => generateRandomColor(index, data.length));

    // Prepare the data for Chart.js
    const chartData = {
        labels: data.map(item => item.name),
        datasets: [{
            data: data.map(item => item.total_time/60),
            backgroundColor: colors,
            borderWidth: 0.5
        }]
    };

    // Destroy existing chart if it exists
    let existingChart = Chart.getChart(ctx);
    if (existingChart) {
        existingChart.destroy();
    }

    // Create the chart
    new Chart(ctx, {
        type: 'doughnut',
        data: chartData,
        options: {
            responsive: true,
            plugins: {
                title: {
                    display: true,
                    text: 'Project Time Distribution'
                },
                legend: {
                    position: 'top',

                }
            },
            cutout: '40%'
        }
    });
}

function bar_graph(data, ctx) {
    // Generate colors dynamically based on the number of data points
    let colors = data.map((element, index) => generateRandomColor(index, data.length));

    // Prepare the data for Chart.js
    const chartData = {
        labels: data.map(item => item.name),
        datasets: [{
            label: 'Project Totals',
            data: data.map(item => item.total_time / 60),
            backgroundColor: colors,
            borderWidth: 0.5
        }]
    };

    // Destroy existing chart if it exists
    let existingChart = Chart.getChart(ctx);
    if (existingChart) {
        existingChart.destroy();
    }

    // Create the chart
    new Chart(ctx, {
        type: 'bar',
        data: chartData,
        options: {
            responsive: true,
            indexAxis: 'y',
        }
    });
}

function scatter_graph(data, ctx) {
    // Extract session dates and durations
    const sessionData = data.map(item => {
        const startTime = new Date(item.start_time);
        const endTime = new Date(item.end_time);
        const duration = (endTime - startTime) / (1000 * 60 * 60); // duration in hours

        return {
            x: endTime,
            y: duration,
            projectName: item.project
        };
    });


    // Group data by project
    const groupedData = Object.entries(
        sessionData.reduce((acc, item) => {
            if (!acc[item.projectName]) acc[item.projectName] = [];
            acc[item.projectName].push(item);
            return acc;
        }, {})
    );

    //sort the grouped data by project name
    groupedData.sort((a, b) => a[0].localeCompare(b[0]));

    // Generate colors based on project names
    const projectColors = {};

    groupedData.map((item, index) => {
        if (!projectColors[item[0]]) {
            projectColors[item[0]] = generateRandomColor(index, groupedData.length);
        }
    });

    console.log(projectColors);

    // Prepare the data for Chart.js
    const chartData = {
        datasets: groupedData.map(([projectName, data]) => ({
            label: projectName,
            data: data,
            backgroundColor: projectColors[projectName],
            pointHoverRadius: 6,
            pointStyle: 'rect',
            pointRotation: 45,
        }))
    };

    // Destroy existing chart if it exists
    let existingChart = Chart.getChart(ctx);
    if (existingChart) {
        existingChart.destroy();
    }

    // Calculate the difference in days between the first and last session
    let endDate = new Date(sessionData[0].x); // array is sorted in descending order
    let startDate  = new Date(sessionData[sessionData.length - 1].x);
    let chartUnit = getChartUnit(endDate, startDate);

    // Create the chart
    new Chart(ctx, {
        type: 'scatter',
        data: chartData,
        options: {
            responsive: true,
            scales: {
                x: {
                    type: 'time',
                    time: {
                        unit: chartUnit
                    },
                    title: {
                        display: true,
                        text: 'Date'
                    }
                },
                y: {
                    title: {
                        display: true,
                        text: 'Duration (hours)'
                    },
                    beginAtZero: true
                }
            },
            plugins: {
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            let label = context.dataset.label || '';
                            if (label) {
                                label += ': ';
                            }
                            if (context.parsed.y !== null) {
                                label += context.parsed.y.toFixed(2) + ' hours';
                            }
                            return label;
                        }
                    }
                }
            }
        }
    });
}

function scatter_subproject_graph(data, ctx) {
  // flatten one point per session‐subproject.
    const pts = [];
    data.forEach(s => {
      const start = new Date(s.start_time);
      const end   = new Date(s.end_time);
      const dur   = (end - start) / (1000 * 60 * 60); // hours
      if ((s.subprojects || []).length) {
        (s.subprojects).forEach(sp => {
          const name = sp.name || sp;
          pts.push({
            x: end,
            y: dur,
            projectName: name
          });
        });
      } else {
        pts.push({
          x: end,
          y: dur,
          projectName: "no subproject"
        });
      }
    });

    // group by subproject name
    const grouped = Object.entries(
    pts.reduce((acc, p) => {
      (acc[p.projectName] = acc[p.projectName]||[]).push(p);
      return acc;
    }, {})
    ).sort((a,b)=>a[0].localeCompare(b[0]));

    // pick a color per subproject
    const colors = {};
    grouped.forEach(([name], i)=> {
    colors[name] = generateRandomColor(i, grouped.length);
    });

    const datasets = grouped.map(([name, arr])=> ({
        label: name,
        data: arr,
        backgroundColor: colors[name],
        pointStyle: 'rect',
        pointRotation: 45,
        pointHoverRadius: 6
    }));

    // destroy old
    const old = Chart.getChart(ctx);
    if (old) old.destroy();

    // figure out time‐unit as before
    const allX = pts.map(p=>p.x).sort((a,b)=>a-b);
    const unit = getChartUnit(allX[allX.length-1], allX[0]);

    new Chart(ctx, {
        type: 'scatter',
        data: { datasets },
        options: {
          responsive: true,
          scales: {
            x: {
              type: 'time',
              time: { unit },
              title: { display: true, text: 'Date' }
            },
            y: {
              beginAtZero: true,
              title: { display: true, text: 'Duration (hours)' }
            }
          },
          plugins: {
            tooltip: {
              callbacks: {
                label(ctx) {
                  const v = ctx.parsed.y.toFixed(2);
                  return `${ctx.dataset.label}: ${v} h`;
                }
              }
            }
          }
        }
    });
}

function calendar_graph(data, ctx, title = "Projects Calendar") {
    // Aggregate data by date
    const dateTotals = data.reduce((acc, item) => {
        let date = new Date(item.start_time).toISOString().split('T')[0];
        let startTime = new Date(item.start_time);
        let endTime = new Date(item.end_time);
        let duration = (endTime - startTime) / (1000 * 60 * 60); // duration in hours

        if (!acc[date]) {
            acc[date] = duration;
        } else {
            acc[date] += duration;
        }
        return acc;
    }, {});

    //console.log("dateTotals: ", dateTotals);

    // let dates = Object.keys(dateTotals).map(date => new Date(date));
    // let minDate = new Date(Math.min(...dates));
    // let maxDate = new Date(Math.max(...dates));

    // sort dates and get the first date
    let year = new Date(Object.keys(dateTotals).sort()[0]).getFullYear();
    let minDate = new Date(year, 0, 1);
    let maxDate = new Date(year + 1, 0, 1);

    const dateList = fillDates(minDate, maxDate);

    // Create data array for each date with their duration
    const chartData = dateList.map(date => {
        let dateStr = date.toISOString().split('T')[0];
        return {
            x: date,
            y: date.getDay(), // 0 is Sunday, 6 is Saturday
            d: dateStr,
            v: dateTotals[dateStr] || 0
        };
    });

    // Find maximum duration for scaling color intensity
    const maxDuration = Math.max(...chartData.map(d => d.v));

    // Destroy existing chart if it exists
    let existingChart = Chart.getChart(ctx);
    if (existingChart) {
        existingChart.destroy();
    }

    // Calculate the difference in days between the first and last session
    let startDate = new Date(chartData[0].x); // array is sorted in descending order
    let endDate  = new Date(chartData[chartData.length - 1].x);
    let chartUnit = getChartUnit(endDate, startDate);

    // Create the chart
    const scales = {
        x: {
            type: 'time',
            position: 'bottom',
            offset: true,
            time: {
                unit: chartUnit,
                round: 'week',
                // displayFormats: {
                //     month: 'MMM dd'
                // }
            },
            ticks: {
                maxRotation: 0
            },
            grid: {
                display: false,
                drawBorder: false
            }
        },
        y: {
            type: 'linear',
            min: 0,
            max: 6,
            reverse: true,
            position: 'left',
            ticks: {
                maxRotation: 0,
                callback: function(value) {
                    return ['Sat', 'Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri'][(value)];
                }
            },
            grid: {
                display: false,
                drawBorder: false,
            }
        }
    };

    new Chart(ctx, {
        type: 'matrix',
        data: {
            datasets: [{
                data: chartData,
                backgroundColor(c) {
                    let value = c.dataset.data[c.dataIndex].v;
                    let alpha = value / maxDuration;
                    if (alpha === 0) {
                        return `rgba(82, 76, 66, 0.37)`;
                    }
                    return `rgba(0, 128, 0, ${alpha})`;
                },
                borderWidth: 1,
                hoverBackgroundColor: 'yellow',
                hoverBorderColor: 'yellowgreen',
                // width(c) {
                //     let a = c.chart.chartArea || {};
                //     return (a.right - a.left) / Math.round(dateList.length/5.5);
                // }
            }]
        },
        options: {
            aspectRatio: 5,
            responsive: true,
            maintainAspectRatio: true,
            plugins: {
                legend: {
                    display: false
                },
                tooltip: {
                    displayColors: true,
                    callbacks: {
                        title() {
                           return ''
                        },
                        label(context) {
                            const data = context.dataset.data[context.dataIndex];
                            return [
                                new Date(data.d).toLocaleDateString('en-US', {
                                    weekday: 'short', // Short day (e.g., Thu)
                                    day: 'numeric',   // Day (e.g., 1, 2, 3)
                                    month: 'short',   // Short month (e.g., Apr)
                                    year: 'numeric'   // Year (e.g., 2023)
                                }),
                                data.v.toFixed(2) + ' hours'
                            ];
                        }
                    }
                },
            },
            scales: scales,
        }
    });
}

function wordcloud(data, ctx, canvasId) {
    // List of common filler words to exclude
    const stopWords = new Set([
        "the", "and", "is", "in", "at", "of", "a", "an", "to", "for", "with",
        "on", "by", "it", "this", "that", "from", "as", "be", "are", "was",
        "were", "has", "have", "had", "but", "or", "not", "which", "we", "you",
        "they", "he", "she", "it", "i", "me", "my", "mine", "your", "yours",
        "about", "if", "so", "then", "there", "here", "where", "when", "how",
        "can", "will", "would", "could", "should", "may", "might", "must",
        "just",
    ]);

    // Extract words from all session notes
    let notesText = data.map(item => item.note || "").join(" ");
    let canvasElement = $(canvasId)[0];

    // Remove Markdown formatting using regex
    const cleanText = notesText
        .replace(/(\*{1,2}|_{1,2}|~{1,2})/g, '') // Remove bold/italic/strikethrough
        .replace(/#{1,6}\s/g, '') // Remove headers
        .replace(/\s+/g, ' ') // Normalize whitespace
        .trim(); // Trim leading/trailing whitespace

    // Count word frequencies, filtering out stop words
    const wordCounts = {};
    cleanText.toLowerCase().replace(/\b\w+\b/g, word => {
        if (!stopWords.has(word) && isNaN(word) && word.length > 2) {
            wordCounts[word] = (wordCounts[word] || 0) + 1;
        }
    });

    // Convert to an array format suitable for wordcloud2.js and limit top N words
    const wordArray = Object.entries(wordCounts)
        .sort((a, b) => b[1] - a[1]) // Sort by frequency
        .slice(0, 100) // Keep top 100 words only
        .map(([text, weight]) => [text, weight]);

    console.log('wordArray:', wordArray);

    //store the width and height of the canvas element from the previous chart
    const container = $('#canvas_container');
    let prev_width = container.clientWidth || window.innerWidth * 0.8; // 80% of viewport width
    let prev_height = container.clientHeight || window.innerHeight * 0.6; // 60% of viewport height

    console.log('prev_width:', prev_width, 'prev_height:', prev_height);


    // Destroy existing chart if it exists
    let existingChart = Chart.getChart(ctx);
    if (existingChart) {
        existingChart.destroy();
    }

    //resize the canvas element to the previous width and height
    canvasElement.width = prev_width;
    canvasElement.height = prev_height

    // Initialize the word cloud
    // set dynamic size by calculating the grid size based on the word array length and canvas width
    let dynamicSize = wordArray.length > 50 ? 8 : 16;
    // set dynamic weight factor based on size of word array frequency
    let largestFrequency = wordArray[0][1]; // get the largest frequency because they are sorted largest to smallest
    let dynamicWeightFactor = dynamicSize * 30 / largestFrequency

    WordCloud(canvasElement, {
        list: wordArray,
        gridSize: Math.round(dynamicSize * canvasElement.width / 1024),
        weightFactor: dynamicWeightFactor,
        fontFamily: 'Times, serif',
        color: function() {
            return 'hsl(' + 360 * Math.random() + ', 100%, 70%)';
        },
        rotateRatio: 0.5,
        rotationSteps: 2,
        backgroundColor: '#f0f0f0'
    });
}

function heatmap_graph(data, ctx) {
    // 1) Prepare storage: 7 days * 24 hours
  const totals = Array.from({ length: 7 }, () => Array(24).fill(0));
  const counts = Array.from({ length: 7 }, () => Array(24).fill(0));

  // 2) Bin each session into hour‐blocks
  data.forEach(item => {
    const t0 = new Date(item.start_time);
    const t1 = new Date(item.end_time);
    let cur = new Date(t0);

    while (cur < t1) {
      const nextHour = new Date(cur);
      nextHour.setHours(cur.getHours() + 1, 0, 0, 0);
      const blockEnd = nextHour < t1 ? nextHour : t1;
      const durHrs   = (blockEnd - cur) / 36e5; // ms→hours

      const wd = cur.getDay();    // 0=Sun…6=Sat
      const hr = cur.getHours();  // 0…23

      totals[wd][hr] += durHrs;
      counts[wd][hr] += 1;

      cur = blockEnd;
    }
  });

  // 3) Build matrix data and find max average
  let maxAvg = 0;
  const matrixData = [];
  for (let wd = 0; wd < 7; wd++) {
    for (let hr = 0; hr < 24; hr++) {
      const cnt = counts[wd][hr];
      const avg = cnt > 0 ? totals[wd][hr] / cnt : 0;
      if (avg > maxAvg) maxAvg = avg;
      matrixData.push({ x: wd, y: hr, v: avg });
    }
  }

  // 5) destroy existing chart
  const old = Chart.getChart(ctx);
  if (old) old.destroy();

  // 6) draw!
  new Chart(ctx, {
    type: 'matrix',
    data: {
      datasets: [{
        label: 'Avg session length (hrs)',
        data: matrixData,
        width(ctx) {
          const c = ctx.chart;
          const area = c.chartArea;
          const full = area ? (area.right - area.left) : c.width;
          return full / 7 - 1;
        },
        height(ctx) {
          const c = ctx.chart;
          const area = c.chartArea;
          const full = area ? (area.bottom - area.top) : c.height;
          return full / 24 - 1;
        },
        backgroundColor(ctx) {
          const v = ctx.dataset.data[ctx.dataIndex].v;
          const alpha = maxAvg ? v / maxAvg : 0;
          return `rgba(0, 128, 0,${alpha})`;
        },
        borderWidth: 0
      }]
    },
    options: {
      responsive: true,
      plugins: {
        title: {
          display: true,
          text: 'Weekly Hourly Heatmap'
        },
        tooltip: {
          callbacks: {
            title() { return ''; },
            label(ctx) {
              const { x: wd, y: hr, v } = ctx.dataset.data[ctx.dataIndex];
              const days = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
              return `${days[wd]} ${hr}:00 → ${(v||0).toFixed(2)} h avg`;
            }
          }
        },
        legend: { display: false }
      },
      scales: {
        x: {
          type: 'linear',
          min: 0,
          max: 6,
          ticks: {
            stepSize: 1,
            callback(v) { return ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'][v]; }
          },
          title: { display: true, text: 'Weekday' },
          grid: { display: false }
        },
        y: {
          type: 'linear',
          min: 0,
          max: 23,
          reverse: true,
          ticks: {
            stepSize: 1,
            callback(v) { return `${v}:00`; }
          },
          title: { display: true, text: 'Time of Day' },
          grid: { display: false }
        }
      }
    }
  });
}

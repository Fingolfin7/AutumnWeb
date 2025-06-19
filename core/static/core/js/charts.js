$(document).ready(function(){
    let selectType = $('#chart_type');
    let draw       = $('#draw');


    // set the default start date to the start of this month
    let current_date = new Date();
    $("#start_date").val(new Date(current_date.getFullYear(), current_date.getMonth(), 1).toISOString().split('T')[0]);
    $("#end_date").val(new Date().toISOString().split('T')[0]);

    function render() {
        let type         = selectType.val();
        let canvas = $('#chart')[0].getContext('2d');

        let start_date = $('#start_date').val();
        let end_date = $('#end_date').val();

        start_date = start_date ? format_date(new Date(start_date)) : "";
        end_date = end_date ? format_date(new Date(end_date)) : "";

        let project_name = $('#project-search').val().trim();

        get_project_data(type, start_date, end_date, project_name)
          .then(data => {
            if (!data.length) {
              console.warn('No data');
              return;
            }

            if (project_name && type === 'scatter'){
                type = 'scatter_subprojects';
            }

            // pick the right drawer
            const chartFns = {
              pie: pie_chart,
              bar: bar_graph,
              scatter: scatter_graph,
              scatter_subprojects: scatter_subproject_graph,
              calendar: calendar_graph,
              wordcloud: wordcloud,
              heatmap: heatmap_graph
            };
             type !== 'wordcloud' ? chartFns[type](data, canvas): chartFns[type](data, canvas, "#chart");
          })
          .catch(console.error);
    }

    // initial draw
    render();
    draw.on('click', render);
});

function get_project_data(type, start_date="", end_date="", project_name=""){
    // by default get the data from all the projects for all time
    let url = ""

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

    const params = [];
    if (project_name)  params.push(`project_name=${project_name}`);
    if (start_date)    params.push(`start_date=${start_date}`);
    if (end_date)      params.push(`end_date=${end_date}`);
    if (params.length) url += '?' + params.join('&');

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
  // 1) figure out your picker dates
  const rawStart = $('#start_date').val();
  const rawEnd   = $('#end_date').val();
  const startDate = rawStart ? new Date(rawStart) : null;
  const endDate   = rawEnd   ? new Date(rawEnd)   : null;

  // 2) bin total hours by [weekday][hour]
  const totals = Array.from({ length: 7 }, () => Array(24).fill(0));
  data.forEach(item => {
    const t0 = new Date(item.start_time);
    const t1 = new Date(item.end_time);
    let cur = new Date(t0);

    // split across hour‐boundaries
    while (cur < t1) {
      const nextHour = new Date(cur);
      nextHour.setHours(cur.getHours() + 1, 0, 0, 0);
      const blockEnd = nextHour < t1 ? nextHour : t1;
      const durHrs   = (blockEnd - cur) / 36e5; // ms → hours

      totals[cur.getDay()][cur.getHours()] += durHrs;
      cur = blockEnd;
    }
  });

  // 3) how many of each weekday in the window? (for averaging)
  const wkCounts = (startDate && endDate)
    ? countWeekdays(startDate, endDate)
    : Array(7).fill(1);

  // 4) build a flat matrix for Chart.js
  let maxAvg = 0;
  const matrixData = [];
  for (let wd = 0; wd < 7; wd++) {
    for (let hr = 0; hr < 24; hr++) {
      const avg = totals[wd][hr] / (wkCounts[wd] || 1);
      maxAvg = Math.max(maxAvg, avg);
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
        label: 'Average hrs/day',
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

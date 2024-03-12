function projects(output, command_args){
    // send the command to the backend
    $.ajax({
        url: 'get_projects/',
        datatype: 'json',
        success: function(data) {
            // iterate through the projects array and append them to the output div
            let active_projects = [];
            let paused_projects = [];
            let completed_projects = [];

            for (let i = 0; i < data.length; i++) {
                let project = data[i];

                if (project.status === 'active'){
                    active_projects.push(project.name);
                }
                else if (project.status === 'paused'){
                    paused_projects.push(project.name);
                }
                else if (project.status === 'completed'){
                    completed_projects.push(project.name);
                }
            }

            if(active_projects.length > 0){
                output.append("<p>Active Projects:</p>");
                for (let i = 0; i < active_projects.length; i++) {
                    if(i === active_projects.length -1){
                        output.append(active_projects[i]);
                    }
                    else{
                        output.append(active_projects[i] + ", ");
                    }
                }
            }

            if(paused_projects.length > 0){
                output.append("<p>Paused Projects:</p>");
                for (let i = 0; i < paused_projects.length; i++) {
                    if(i === paused_projects.length -1){
                        output.append(paused_projects[i]);
                    }
                    else{
                        output.append(paused_projects[i] + ", ");
                    }
                }
            }

            if(completed_projects.length > 0){
                output.append("<p>Completed Projects:</p>");
                for (let i = 0; i < completed_projects.length; i++) {
                    if(i === paused_projects.length -1){
                        output.append(completed_projects[i]);
                    }
                    else{
                        output.append(completed_projects[i] + ", ");
                    }
                }
            }

        }
    })
}

function start(output, command_args){
    // get the project name and subprojects to send to the backend
    let post_data = {
        'name': command_args[0],
        'subprojects': command_args.slice(1)
    };

    console.log(post_data['name']);
    console.log(post_data['subprojects']);

    // check if the project name is in the list of projects (get_projects)
    $.ajax({
        url: 'get_projects/',
        datatype: 'json',
        success: function(data) {
            if (!data.includes(post_data['name'])){
                output.append("<p> <span class='highlight-project'>" + post_data['name'] + "</span> does not exist." +
                    "Create it? \n[Y/n]: </p>");

                // get the user's response
                let create_project = prompt("Create project? [Y/n]");
                if (create_project.toLowerCase() === 'y'){
                    console.log('Here');
                    $.ajax({
                        url: 'create_project/',
                        method: 'POST',
                        data: JSON.stringify(post_data),
                        contentType: 'application/json',  // Add this line
                        datatype: 'json',
                        success: function(data){
                            output.append("<p> Created <span class='highlight-project'>" + post_data['name'] + "</span>" +
                                format_subprojects(post_data['subprojects']) + "</p>")

                            // send the command to the backend
                            $.ajax({
                                url: 'start/',
                                method: 'POST',
                                data: JSON.stringify(post_data),
                                contentType: 'application/json',  // Add this line
                                datatype: 'json',
                                success: function(data){
                                    output.append("<p> Started <span class='highlight-project'>" + post_data['name'] + "</span>" +
                                        format_subprojects(post_data['subprojects']) + "</p>")
                                },
                                error: function(data){
                                    output.append("<p> Error: " + data + "</p>")
                                }

                            });
                        },
                        error: function(data){
                            output.append("<p> Error: " + data['responseJSON']['detail'] + "</p>")
                        }
                    });
                }
            }
            else{
                // send the command to the backend
                $.ajax({
                    url: 'start/',
                    method: 'POST',
                    data: JSON.stringify(post_data),
                    contentType: 'application/json',  // Add this line
                    datatype: 'json',
                    success: function(data){
                        output.append("<p> Started <span class='highlight-project'>" + post_data['name'] + "</span>" +
                            format_subprojects(post_data['subprojects']) + "</p>")
                    },
                    error: function(data){
                        output.append("<p> Error: " + data + "</p>")
                    }

                });
            }
        }
    });


}
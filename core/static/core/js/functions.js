function projects(output){
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
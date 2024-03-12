function format_subprojects(subprojects){
    let formatted_subprojects = "[";
    for (let i = 0; i < subprojects.length; i++) {
        if(i === subprojects.length -1){
            formatted_subprojects += "<span class='highlight-subs'>" + subprojects[i] + "</span>";
        }
        else{
            formatted_subprojects += "<span class='highlight-subs'>" + subprojects[i] + "</span>" + ", ";
        }
    }
    formatted_subprojects += "]";
    return formatted_subprojects;
}
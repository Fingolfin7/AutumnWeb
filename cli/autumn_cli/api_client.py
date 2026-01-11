"""API client for communicating with AutumnWeb API."""

import requests
from typing import Optional, Dict, List, Any
from .config import get_api_key, get_base_url


class APIError(Exception):
    """Exception raised for API errors."""
    pass


class APIClient:
    """Client for AutumnWeb API."""
    
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        self.api_key = api_key or get_api_key()
        self.base_url = (base_url or get_base_url()).rstrip("/")
        
        if not self.api_key:
            raise APIError("API key not configured. Run 'autumn auth setup' first.")
    
    def _headers(self) -> Dict[str, str]:
        """Get request headers with authentication."""
        return {
            "Authorization": f"Token {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
    
    def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Make HTTP request to API."""
        url = f"{self.base_url}{endpoint}"
        
        try:
            response = requests.request(
                method=method,
                url=url,
                headers=self._headers(),
                params=params,
                json=json,
                timeout=30,
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            if response.status_code == 401:
                raise APIError("Authentication failed. Check your API key.")
            try:
                error_data = response.json()
                error_msg = error_data.get("error", str(e))
                raise APIError(f"API error: {error_msg}")
            except:
                raise APIError(f"API error: {e}")
        except requests.exceptions.RequestException as e:
            raise APIError(f"Network error: {e}")
    
    # Timer endpoints
    
    def start_timer(self, project: str, subprojects: Optional[List[str]] = None, note: Optional[str] = None) -> Dict:
        """Start a new timer."""
        data = {"project": project}
        if subprojects:
            data["subprojects"] = subprojects
        if note:
            data["note"] = note
        return self._request("POST", "/api/timer/start/", json=data)
    
    def stop_timer(self, session_id: Optional[int] = None, project: Optional[str] = None, note: Optional[str] = None) -> Dict:
        """Stop the current timer."""
        data = {}
        if session_id:
            data["session_id"] = session_id
        if project:
            data["project"] = project
        if note is not None:
            data["note"] = note
        return self._request("POST", "/api/timer/stop/", json=data)
    
    def get_timer_status(self, session_id: Optional[int] = None, project: Optional[str] = None) -> Dict:
        """Get status of active timer(s)."""
        params = {}
        if session_id:
            params["session_id"] = session_id
        if project:
            params["project"] = project
        return self._request("GET", "/api/timer/status/", params=params)
    
    def restart_timer(self, session_id: Optional[int] = None, project: Optional[str] = None) -> Dict:
        """Restart a timer."""
        data = {}
        if session_id:
            data["session_id"] = session_id
        if project:
            data["project"] = project
        return self._request("POST", "/api/timer/restart/", json=data)
    
    def delete_timer(self, session_id: Optional[int] = None) -> Dict:
        """Delete a timer."""
        params = {}
        if session_id:
            params["session_id"] = session_id
        return self._request("DELETE", "/api/timer/delete/", params=params)
    
    # Session endpoints
    
    def log_activity(
        self,
        period: Optional[str] = None,
        project: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Dict:
        """Get activity logs."""
        params = {"compact": "false"}
        if period:
            params["period"] = period
        if project:
            params["project"] = project
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        return self._request("GET", "/api/log/", params=params)
    
    def search_sessions(
        self,
        project: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        note_snippet: Optional[str] = None,
        active: Optional[bool] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> Dict:
        """Search sessions."""
        params = {}
        if project:
            params["project"] = project
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        if note_snippet:
            params["note_snippet"] = note_snippet
        if active is not None:
            params["active"] = str(active).lower()
        if limit:
            params["limit"] = limit
        if offset:
            params["offset"] = offset
        return self._request("GET", "/api/sessions/search/", params=params)
    
    def track_session(
        self,
        project: str,
        start: str,
        end: str,
        subprojects: Optional[List[str]] = None,
        note: Optional[str] = None,
    ) -> Dict:
        """Track a completed session."""
        data = {
            "project": project,
            "start": start,
            "end": end,
        }
        if subprojects:
            data["subprojects"] = subprojects
        if note:
            data["note"] = note
        return self._request("POST", "/api/track/", json=data)
    
    # Project endpoints
    
    def list_projects_grouped(self, start_date: Optional[str] = None, end_date: Optional[str] = None) -> Dict:
        """List projects grouped by status."""
        params = {"compact": "false"}  # Request full project metadata
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        return self._request("GET", "/api/projects/grouped/", params=params)
    
    def create_project(self, name: str, description: Optional[str] = None) -> Dict:
        """Create a new project."""
        data = {"name": name}
        if description:
            data["description"] = description
        return self._request("POST", "/api/create_project/", json=data)
    
    def list_subprojects(self, project: str) -> Dict:
        """List subprojects for a project."""
        params = {"project": project}
        return self._request("GET", "/api/subprojects/", params=params)
    
    # Chart/analytics endpoints
    
    def tally_by_sessions(
        self,
        project_name: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[Dict]:
        """Get project totals (for charts)."""
        params = {}
        if project_name:
            params["project_name"] = project_name
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        return self._request("GET", "/api/tally_by_sessons/", params=params)  # Note: typo in API endpoint
    
    def tally_by_subprojects(
        self,
        project_name: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[Dict]:
        """Get subproject totals (for charts)."""
        params = {"project_name": project_name}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        return self._request("GET", "/api/tally_by_subprojects/", params=params)
    
    def list_sessions(
        self,
        project_name: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[Dict]:
        """List sessions (for charts)."""
        params = {}
        if project_name:
            params["project_name"] = project_name
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        return self._request("GET", "/api/list_sessions/", params=params)

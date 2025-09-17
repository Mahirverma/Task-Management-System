async function updateTaskStatus(employeeId, taskId, status) {
	if (!confirm('Change task status?')) return;
	const res = await fetch(`/employee/${employeeId}/tasks/${taskId}`, {
		method: 'PATCH',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ status })
	});
	if (res.ok) location.reload();
	else {
		const d = await res.json().catch(()=>({detail:'Unknown error'}));
		alert(d.detail || JSON.stringify(d));
	}
}

async function deactivateEmployee(managerId, employeeId) {
	if (!confirm('Deactivate this employee?')) return;
	const res = await fetch(`/manager/${managerId}/users/${employeeId}/deactivate`, { method: 'PATCH' });
	if (res.ok) location.reload();
	else {
		const d = await res.json().catch(()=>({detail:'Unknown error'}));
		alert(d.detail || JSON.stringify(d));
	}
}

async function activateEmployee(managerId, employeeId) {
	if (!confirm('Activate this employee?')) return;
	const res = await fetch(`/manager/${managerId}/users/${employeeId}/activate`, { method: 'PATCH' });
	if (res.ok) location.reload();
	else {
		const d = await res.json().catch(()=>({detail:'Unknown error'}));
		alert(d.detail || JSON.stringify(d));
	}
}

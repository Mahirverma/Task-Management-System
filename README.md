# Task Management System

A FastAPI-based Task Management System with role-based access (Admin, Manager, Employee).  
Supports authentication, task assignment, simple dashboards (Jinja2), and a developer-friendly local setup.

---

## 🚀 What this is

This project provides a lightweight task management backend + basic frontend templates.  
It includes:

- Role-based access (Admin / Manager / Employee)
- JWT authentication (cookie or header)
- Manager → Employee relationship and task assignment
- HTML pages with Jinja2 templates and Bootstrap
- SQLAlchemy ORM (optionally Alembic for migrations)

---

## ⚡ Features

- Create/assign/track tasks
- Admin can create managers
- Managers can create employees and tasks
- Employees see tasks assigned to them
- Simple dashboards for each role
- Reset password / profile edit pages
- Lightweight, easy to run locally

---

## ✅ Prerequisites

- Python 3.10+ (recommended)
- Git
- A database (PostgreSQL also supported via `DATABASE_URL`)
- Optional: `virtualenv` (or just use `python -m venv`)

---

## 🛠 Setup — Local Development

### 1. Clone repository
```bash
git clone https://github.com/your-username/task-management-system.git
cd task-management-system
"""Combine endpoint routers into the application's versioned API."""

from fastapi import APIRouter

from app.api.routes import activity, auth, projects, tasks, users

api_router = APIRouter()
# Keep each feature's routes in its own module and register them here.
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(users.roles_router)
api_router.include_router(projects.router)
api_router.include_router(tasks.router)
api_router.include_router(activity.router)

# accounts_app

## Purpose

- Accounts, roles and the token auth cycle for the whole API, mounted at `api/` in `config/urls.py`: `auth/register/`, `auth/token/`, `auth/logout/`, `users/`, `users/<id>/`
- No models of its own: Django `auth.User` + DRF `authtoken.Token` (tables in `public`), so no migrations

## Ownership

- `serializers.py` — `ROLE_ADMIN` / `ROLE_USER`; `RoleField` (`role` over `User.is_staff`: `admin` = staff); `UserSerializer` (`id`, `username`, `role`; only `role` writable); `RegisterSerializer` (`username`, write-only `password` checked by Django `validate_password`, errors under `password`; always creates a non-staff user)
- `views.py`:
  - `RegisterView` — POST, open (`AllowAny`, no authentication classes so a stale token header doesn't block it), `201` with the user
  - `LogoutView` — POST, any authenticated role, deletes the user's token (one token per user, so every session ends), `204`
  - `UserListView` (GET, `search` on `username`, `UserPagination` 20/max 100) and `UserDetailView` (GET / PATCH `role` / DELETE), both `IsAdmin`; PATCH or DELETE on yourself is `409` so an admin always remains; no PUT
- `urls.py` — the routes above; `auth/token/` is DRF `obtain_auth_token` (`{"token"}`, wrong credentials `400 non_field_errors`)
- `tests.py` — `RegisterTests`, `LoginLogoutTests`, `AuthRequiredTests` (`401` on every endpoint), `UserRoleTests` (role `user`: reads ok, writes / live reads / `users/` → `403`), `UserAdminTests`

## Local Contracts

- Roles: `admin` = `User.is_staff` (superusers from `createsuperuser` are staff), anything else = `user`; no role model or field
- Global DRF defaults (`config/settings.py`): `TokenAuthentication` + `src.utils.permissions.IsAdminOrReadOnly` (authenticated; safe methods for every role, other methods admin only); views needing admin even on GET set `permission_classes = [IsAdmin]` (`users/`, `apps/<id>/evaluate/`, `energy/current/` — live inverter reads that store a snapshot)
- Registration never grants admin (`role` / `is_staff` in the body are ignored); admins promote at `PATCH /api/users/<id>/`
- Tokens don't expire; logout is the only revocation
- Keep `postman/specs/director-api.yaml` and the `postman/collections/DirectorApp` `Auth` / `Users` requests + examples in sync

## Work Guidance

- API tests use `src.utils.testing.operator_client(username, admin=True|False)` (real token); unauthenticated cases use a bare `APIClient()`

## Verification

- `uv run python manage.py test src.accounts_app`

## Child DOX Index

- None

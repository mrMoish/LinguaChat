import os
import secrets

from dotenv import load_dotenv

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Request,
)

load_dotenv()

router = APIRouter()

ADMIN_SECRET = os.getenv("ADMIN_SECRET")

print("ADMIN_SECRET configured:", bool(ADMIN_SECRET))
print("ADMIN_SECRET length:", len(ADMIN_SECRET) if ADMIN_SECRET else 0)


async def require_admin(
    authorization: str = Header(default=""),
):
    if not ADMIN_SECRET:
        raise HTTPException(
            status_code=500,
            detail="ADMIN_SECRET is not configured",
        )

    expected = f"Bearer {ADMIN_SECRET}"

    if not secrets.compare_digest(
        authorization,
        expected,
    ):
        raise HTTPException(
            status_code=401,
            detail="Unauthorized",
        )


# ============================================================
# USERS
# ============================================================

@router.get("/users")
async def get_users(
    request: Request,
    page: int = 1,
    limit: int = 20,
    _: None = Depends(require_admin),
):
    try:
        if page < 1:
            page = 1

        if limit < 1:
            limit = 20

        if limit > 100:
            limit = 100

        offset = (page - 1) * limit

        db_pool = getattr(
            request.app.state,
            "db_pool",
            None,
        )

        if not db_pool:
            raise HTTPException(
                status_code=503,
                detail="Database pool is not available",
            )

        async with db_pool.acquire() as conn:
            total_users = await conn.fetchval(
                """
                SELECT COUNT(DISTINCT session_id)
                FROM chat_history
                WHERE session_id IS NOT NULL
                """
            )

            users = await conn.fetch(
                """
                WITH message_stats AS (
                    SELECT
                        session_id,
                        COUNT(*) AS message_count
                    FROM chat_history
                    WHERE session_id IS NOT NULL
                    GROUP BY session_id
                ),

                last_user_message AS (
                    SELECT DISTINCT ON (session_id)
                        session_id,
                        content AS last_user_message,
                        created_at AS last_user_message_at
                    FROM chat_history
                    WHERE
                        session_id IS NOT NULL
                        AND role = 'user'
                    ORDER BY
                        session_id,
                        created_at DESC,
                        id DESC
                )

                SELECT
                    message_stats.session_id,
                    message_stats.message_count,
                    last_user_message.last_user_message,
                    last_user_message.last_user_message_at

                FROM message_stats

                LEFT JOIN last_user_message
                    ON message_stats.session_id =
                       last_user_message.session_id

                ORDER BY
                    last_user_message.last_user_message_at
                    DESC NULLS LAST

                LIMIT $1
                OFFSET $2
                """,
                limit,
                offset,
            )

        return {
            "total_users": total_users,
            "page": page,
            "limit": limit,
            "users": [
                {
                    "session_id": str(
                        row["session_id"]
                    ),
                    "message_count": row[
                        "message_count"
                    ],
                    "last_user_message": row[
                        "last_user_message"
                    ],
                    "last_user_message_at": row[
                        "last_user_message_at"
                    ],
                }
                for row in users
            ],
        }

    except HTTPException:
        raise

    except Exception as e:
        print(
            f"ADMIN /users ERROR: "
            f"{type(e).__name__}: {e}"
        )

        raise HTTPException(
            status_code=500,
            detail=f"{type(e).__name__}: {e}",
        )



# ============================================================
# USER HISTORY
# ============================================================

@router.get("/users/{session_id}/history")
async def get_admin_user_history(
    session_id: str,
    request: Request,
    _: None = Depends(require_admin),
):
    # --------------------------------------------------------
    # Validate UUID
    # --------------------------------------------------------

    try:
        import uuid

        session_uuid = uuid.UUID(session_id)

    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Invalid session ID",
        )

    # --------------------------------------------------------
    # Database pool
    # --------------------------------------------------------

    db_pool = getattr(request.app.state, "db_pool", None)

    if not db_pool:
        raise HTTPException(
            status_code=503,
            detail="Database is not connected",
        )

    # --------------------------------------------------------
    # Get history
    # --------------------------------------------------------

    async with db_pool.acquire() as conn:

        messages = await conn.fetch(
            """
            SELECT
                id,
                role,
                content,
                message_type,
                media_url,
                created_at
            FROM chat_history
            WHERE session_id = $1
            ORDER BY
                created_at ASC,
                id ASC
            """,
            session_uuid,
        )

    # --------------------------------------------------------
    # Response
    # --------------------------------------------------------

    return {
        "session_id": session_id,
        "messages": [
            {
                "id": row["id"],
                "role": row["role"],
                "content": row["content"],
                "message_type": (
                    row["message_type"]
                    or "text"
                ),
                "media_url": row["media_url"],
                "created_at": row["created_at"],
            }
            for row in messages
        ],
    }
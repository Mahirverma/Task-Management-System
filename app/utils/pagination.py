from fastapi import Query, HTTPException, status

def get_pagination_params(
    skip: int = Query(0, ge=0), 
    limit: int = Query(40, ge=1, le=100)
):
    if limit > 100:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Limit cannot exceed 100")
    return {"skip": skip, "limit": limit}
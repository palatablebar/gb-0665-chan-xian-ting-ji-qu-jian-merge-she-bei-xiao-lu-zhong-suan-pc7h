from fastapi import HTTPException
class DomainError(ValueError):
    def __init__(self,code,detail):
        self.code=code
        super().__init__(detail)
def reject(code,detail):
    raise DomainError(code,detail)
def status_for(code):
    # 版本状态类冲突返回409，内容/参数类问题返回422。
    return 409 if code in {"STALE_VERSION","STATE","LOCKED","APPROVAL","COVERAGE"} else 422
def http_error(exc):
    return HTTPException(status_for(exc.code),detail={"code":exc.code,"message":str(exc)})

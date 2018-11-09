from django.contrib.auth import authenticate, login
from django.shortcuts import redirect

def UserLoginView(request):
    username = request.POST['username']
    password = request.POST['password']
    user = authenticate(request, username=username, password=password)
    if user is not None:
        login(request, user)  # using Django’s session framework.
        # Redirect to a success page.
        return redirect('/autors/')
    else:
        # Return an 'invalid login' error message.
        return redirect('/login/')



import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardHeader, CardContent, CardFooter } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { useToast } from "@/components/ui/use-toast";
import { api, getSession } from "@/lib/api";
import { Link } from "react-router-dom";

const Login = () => {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();
  const { toast } = useToast();

  // If a valid token is already stored, go straight to the right page
  useEffect(() => {
    if (getSession()) {
      redirectBasedOnRole();
    }
  }, [navigate]);

  // The role comes from the token (a display hint; the server decides access)
  const redirectBasedOnRole = () => {
    if (getSession()?.role === "admin") {
      toast({
        title: "Welcome Admin",
        description: "You've been logged in as an administrator",
      });
      navigate("/admin");
    } else {
      toast({
        title: "Login successful!",
        description: "Welcome back!",
      });
      navigate("/elections");
    }
  };

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);

    try {
      console.log('Starting login process for:', email);
      
      const session = await api.login(email, password);

      if (session) {
        redirectBasedOnRole();
        toast({
          title: "Login successful!",
          description: "Redirecting you to the appropriate dashboard...",
        });
      } else {
        throw new Error('Login failed - no user data returned');
      }
    } catch (error: any) {
      console.error('Login error:', error);
      
      let errorMessage = "Login failed";
      
      // API errors carry the server's own message; anything else stays generic
      if (typeof error?.status === "number" && error.message) {
        errorMessage = error.message;
      }
      
      toast({
        title: "Error",
        description: errorMessage,
        variant: "destructive",
      });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 py-12 px-4 sm:px-6 lg:px-8">
      <Card className="w-full max-w-md">
        <CardHeader className="space-y-1">
          <h2 className="text-2xl font-bold text-center">Welcome back</h2>
          <p className="text-sm text-muted-foreground text-center">
            Enter your credentials to access your account
          </p>
        </CardHeader>
        <form onSubmit={handleLogin}>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                placeholder="m@example.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </div>
          </CardContent>
          <CardFooter className="flex flex-col space-y-4">
            <Button
              type="submit"
              className="w-full"
              disabled={loading}
            >
              {loading ? "Logging in..." : "Log in"}
            </Button>
            <p className="text-sm text-center text-gray-600">
              Don't have an account?{" "}
              <Link to="/register" className="text-primary hover:underline">
                Sign up
              </Link>
            </p>
          </CardFooter>
        </form>
      </Card>
    </div>
  );
};

export default Login;

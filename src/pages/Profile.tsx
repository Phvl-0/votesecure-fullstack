
import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import Layout from "@/components/Layout";
import { api, getSession } from "@/lib/api";
import { useToast } from "@/components/ui/use-toast";
import { User, ListChecks } from "lucide-react";

const Profile = () => {
  const navigate = useNavigate();
  const { toast } = useToast();
  const [loading, setLoading] = useState(true);
  const [userDetails, setUserDetails] = useState<any>(null);
  const [voteHistory, setVoteHistory] = useState<any[]>([]);

  useEffect(() => {
    const checkAuth = async () => {
      const session = getSession();
      
      if (!session) {
        toast({
          title: "Authentication required",
          description: "Please log in to view your profile",
          variant: "destructive",
        });
        navigate("/login");
        return;
      }
      
      fetchUserData();
    };

    checkAuth();
  }, [navigate, toast]);

  const fetchUserData = async () => {
    try {
      setLoading(true);
      
      // Email and role come from the token (a display hint; the server enforces access).
      // The history is the caller's own votes, taken from the token on the server.
      const session = getSession();
      const votes = await api.myVotes();

      setUserDetails({
        email: session?.email,
        isAdmin: session?.role === "admin",
      });

      setVoteHistory(votes || []);
    } catch (error) {
      console.error('Error fetching user data:', error);
      toast({
        title: "Error",
        description: "Failed to load your profile data",
        variant: "destructive",
      });
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <Layout>
        <div className="flex justify-center items-center h-64">
          <p>Loading profile...</p>
        </div>
      </Layout>
    );
  }

  return (
    <Layout>
      <div className="grid gap-6">
        <Card>
          <CardHeader>
            <CardTitle className="text-2xl">My Profile</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex flex-col md:flex-row gap-4 items-start">
              <div className="bg-primary/10 p-8 rounded-full">
                <User className="w-20 h-20 text-primary" />
              </div>
              <div>
                <h2 className="text-xl font-semibold mb-2">{userDetails?.email}</h2>
                <div className="flex gap-2 mb-4">
                  <Badge variant="outline">{userDetails?.isAdmin ? "Admin" : "Voter"}</Badge>
                </div>
                <Button
                  variant="outline"
                  onClick={() => navigate("/elections")}
                >
                  View Available Elections
                </Button>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <ListChecks className="w-5 h-5" />
              Voting History
            </CardTitle>
            <CardDescription>Your past voting activity</CardDescription>
          </CardHeader>
          <CardContent>
            {voteHistory.length === 0 ? (
              <p className="text-center text-gray-500 py-4">You haven't voted in any elections yet.</p>
            ) : (
              <div className="space-y-4">
                {voteHistory.map((vote) => (
                  <div key={vote.id} className="border rounded-md p-4">
                    <div className="flex justify-between items-start mb-2">
                      <h3 className="font-medium">{vote.elections?.title}</h3>
                      <Badge>{vote.elections?.status}</Badge>
                    </div>
                    <p className="text-sm text-gray-600">Your vote was recorded. Ballots are secret, so your choice is not shown.</p>
                    <p className="text-sm text-gray-500 mt-2">
                      {new Date(vote.created_at).toLocaleDateString()} at {new Date(vote.created_at).toLocaleTimeString()}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </Layout>
  );
};

export default Profile;
